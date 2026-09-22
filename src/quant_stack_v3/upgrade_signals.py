"""Causal upgrade signals and daily exposure residuals on a supplied eligible universe."""

from __future__ import annotations

import numpy as np
import pandas as pd

UPGRADE_SIGNALS = ("MOM_60_5", "COND_REV_5", "DOWNSIDE_60", "ROBUST_TREND")
EXPOSURES = ("beta60", "vol60", "log_amount60")


def build_upgrade_signals(bars: pd.DataFrame, eligible: pd.DataFrame) -> pd.DataFrame:
    """Compute trailing signals on caller-supplied daily eligible symbol/session pairs.

    ``bars`` supplies session, symbol, session_ordinal, calc_close and amount.
    ``eligible`` supplies the complete point-in-time top-300 universe, including
    historical sessions needed for the market proxy. No universe is inferred or
    backfilled here. Raw unavailable values and their scores/ranks remain NaN.
    Signals observed at T are for execution no earlier than T+1.

    MOM is log(P[t-5]/P[t-60]); conditional reversal is -log(P[t]/P[t-5]),
    gated by amount20 >= the daily median and RMS vol20 <= the daily 75th
    percentile. Downside is -sqrt(252 * mean(min(log return, 0)**2, 60)).
    Robust trend averages the daily population z-scores of MOM and downside.
    A missing trading session invalidates any window crossing that gap.
    """
    frame = (
        bars.loc[:, ["session", "symbol", "session_ordinal", "calc_close", "amount"]]
        .sort_values(["symbol", "session"], kind="stable")
        .reset_index(drop=True)
    )
    grouped = frame.groupby("symbol", sort=True)
    ordinal = frame["session_ordinal"]
    continuous_1 = ordinal.sub(grouped["session_ordinal"].shift(1)).eq(1)
    continuous_5 = ordinal.sub(grouped["session_ordinal"].shift(5)).eq(5)
    continuous_20 = ordinal.sub(grouped["session_ordinal"].shift(19)).eq(19)
    continuous_60 = ordinal.sub(grouped["session_ordinal"].shift(59)).eq(59)
    continuous_61 = ordinal.sub(grouped["session_ordinal"].shift(60)).eq(60)
    frame["return_1"] = pd.Series(
        np.log(frame["calc_close"] / grouped["calc_close"].shift(1)), index=frame.index
    ).where(continuous_1)
    frame["MOM_60_5"] = pd.Series(
        np.log(grouped["calc_close"].shift(5) / grouped["calc_close"].shift(60)), index=frame.index
    ).where(continuous_61)
    frame["COND_REV_5"] = -pd.Series(
        np.log(frame["calc_close"] / grouped["calc_close"].shift(5)), index=frame.index
    ).where(continuous_5)
    for window, continuous in ((20, continuous_20), (60, continuous_60)):
        frame[f"mean_amount_{window}"] = (
            grouped["amount"]
            .transform(
                lambda values, window=window: values.rolling(window, min_periods=window).mean()
            )
            .where(continuous)
        )
        frame[f"vol{window}"] = grouped["return_1"].transform(
            lambda values, window=window: np.sqrt(
                values.pow(2).rolling(window, min_periods=window).mean() * 252
            )
        )
    frame["DOWNSIDE_60"] = grouped["return_1"].transform(
        lambda values: -np.sqrt(values.clip(upper=0).pow(2).rolling(60).mean() * 252)
    )
    frame["log_amount60"] = np.log(frame["mean_amount_60"].where(frame["mean_amount_60"] > 0))

    keys = eligible.loc[:, ["session", "symbol"]]
    members = keys.merge(frame, on=["session", "symbol"], how="left", validate="one_to_one")
    market_groups = members.groupby("session", sort=True)["return_1"]
    market = market_groups.mean().where(market_groups.count().eq(market_groups.size()))
    frame["market_return"] = frame["session"].map(market)
    frame["beta60"] = np.nan
    for _, positions in frame.groupby("symbol", sort=True).groups.items():
        stock = frame.loc[positions, "return_1"]
        proxy = frame.loc[positions, "market_return"]
        frame.loc[positions, "beta60"] = (
            stock.rolling(60).cov(proxy).div(proxy.rolling(60).var().replace(0.0, np.nan))
        )
    frame["beta60"] = frame["beta60"].where(continuous_61)
    result = keys.merge(frame, on=["session", "symbol"], how="left", validate="one_to_one")
    result = result.sort_values(["session", "symbol"], kind="stable").reset_index(drop=True)
    for signal in UPGRADE_SIGNALS:
        result[f"{signal}_score"] = np.nan
        result[f"{signal}_rank"] = np.nan
    result["ROBUST_TREND"] = np.nan
    for _, positions in result.groupby("session", sort=True).groups.items():
        day = result.loc[positions]
        for signal in ("MOM_60_5", "DOWNSIDE_60"):
            if np.isfinite(day[signal]).all():
                _assign_score(result, positions, signal, _zscore(day[signal]))
            else:
                result.loc[positions, signal] = np.nan
        components = result.loc[positions, ["MOM_60_5_score", "DOWNSIDE_60_score"]]
        if np.isfinite(components).all().all():
            robust = components.mean(axis=1)
            result.loc[positions, "ROBUST_TREND"] = robust
            _assign_score(result, positions, "ROBUST_TREND", robust)
        gate_columns = ["mean_amount_20", "vol20", "COND_REV_5"]
        result.loc[positions, "COND_REV_5"] = np.nan
        if np.isfinite(day.loc[:, gate_columns]).all().all():
            mask = day["mean_amount_20"].ge(day["mean_amount_20"].median()) & day["vol20"].le(
                day["vol20"].quantile(0.75)
            )
            candidates = day.loc[mask, "COND_REV_5"]
            if len(candidates) >= 50:
                result.loc[candidates.index, "COND_REV_5"] = candidates
                _assign_score(result, candidates.index, "COND_REV_5", _zscore(candidates))
    return result


def residualize_scores(
    scores: pd.DataFrame, score_column: str = "score", minimum_cross_section: int = 50
) -> pd.DataFrame:
    """Regress daily scores on intercept and z(beta60, vol60, log_amount60).

    Keep only jointly finite rows; omit days with fewer than 50 rows by default.
    NumPy least squares handles rank-deficient exposure matrices. Rank residuals
    descending with symbol-ascending tie breaks. Inputs are never modified.
    """
    frame = scores.sort_values(["session", "symbol"], kind="stable").copy()
    finite = pd.Series(
        np.isfinite(frame.loc[:, [score_column, *EXPOSURES]].to_numpy(dtype=float)).all(axis=1),
        index=frame.index,
    )
    frame = frame.loc[finite].copy()
    sizes = frame.groupby("session", sort=True)["symbol"].transform("size")
    frame = frame.loc[sizes >= minimum_cross_section].reset_index(drop=True)
    frame["residual_score"] = np.nan
    frame["residual_rank"] = np.nan
    for _, positions in frame.groupby("session", sort=True).groups.items():
        day = frame.loc[positions]
        exposures = day.loc[:, list(EXPOSURES)].apply(_zscore)
        design = np.column_stack([np.ones(len(day)), exposures.to_numpy(dtype=float)])
        target = day[score_column].to_numpy(dtype=float)
        coefficients = np.linalg.lstsq(design, target, rcond=None)[0]
        residuals = pd.Series(target - design @ coefficients, index=day.index)
        frame.loc[positions, "residual_score"] = residuals
        frame.loc[positions, "residual_rank"] = residuals.rank(method="first", ascending=False)
    return frame.sort_values(["session", "residual_rank", "symbol"], kind="stable")


def _zscore(values: pd.Series) -> pd.Series:
    if values.max() == values.min():
        return pd.Series(0.0, index=values.index)
    deviation = float(values.std(ddof=0))
    if deviation == 0:
        return pd.Series(0.0, index=values.index)
    return (values - values.mean()) / deviation


def _assign_score(frame: pd.DataFrame, positions: pd.Index, signal: str, scores: pd.Series) -> None:
    frame.loc[positions, f"{signal}_score"] = scores
    frame.loc[positions, f"{signal}_rank"] = scores.rank(method="first", ascending=False)
