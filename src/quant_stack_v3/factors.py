"""Causal AF-003 factor calculation and dynamic-liquidity scoring."""

from __future__ import annotations

from collections.abc import Sequence

import numpy as np
import pandas as pd

from quant_stack_v3.protocol import ALPHAS, Protocol

REQUIRED_COLUMNS = (
    "session",
    "symbol",
    "calc_high",
    "calc_low",
    "calc_close",
    "calc_volume",
    "amount",
    "st",
    "suspended",
    "session_ordinal",
    "listed_sessions",
)


def build_scores(bars: pd.DataFrame, protocol: Protocol) -> pd.DataFrame:
    """Return one deterministic daily score table from causal historical bars."""
    _require_columns(bars, REQUIRED_COLUMNS)
    frame = bars.sort_values(["symbol", "session"], kind="stable").copy()
    grouped = frame.groupby("symbol", sort=True, group_keys=False)
    frame["mean_amount_20"] = grouped["amount"].transform(
        lambda item: item.rolling(20, min_periods=20).mean()
    )
    frame["mean_amount_60"] = grouped["amount"].transform(
        lambda item: item.rolling(60, min_periods=60).mean()
    )
    previous_close = grouped["calc_close"].shift(1)
    frame["return_1"] = frame["calc_close"] / previous_close - 1.0
    frame["abs_return_volume"] = frame["return_1"].abs() * frame["calc_volume"]
    frame["CN_REV_001"] = grouped["calc_close"].transform(_rolling_beta5)
    frame["CN_REV_003"] = grouped["return_1"].transform(_rolling_cntd5)
    frame["CN_PV_003"] = (
        grouped["calc_volume"].transform(lambda item: item.rolling(20, min_periods=20).mean())
        / frame["calc_volume"]
    )
    frame["CN_RANGE_001"] = grouped.apply(  # type: ignore[call-overload]
        _rolling_range20, include_groups=False
    ).reset_index(level=0, drop=True)
    q_mean = grouped["abs_return_volume"].transform(
        lambda item: item.rolling(20, min_periods=20).mean()
    )
    q_std = grouped["abs_return_volume"].transform(
        lambda item: item.rolling(20, min_periods=20).std(ddof=1)
    )
    frame["CN_VOL_003"] = -q_std / (q_mean + 1e-12)
    frame["CN_VOL_002"] = (
        -grouped["calc_close"].transform(lambda item: item.rolling(60, min_periods=60).std(ddof=1))
        / frame["calc_close"]
    )
    frame["CN_PV_004"] = (
        -grouped["calc_volume"].transform(lambda item: item.rolling(20, min_periods=20).std(ddof=1))
        / frame["calc_volume"]
    )
    frame["consecutive_60"] = frame["session_ordinal"] - grouped["session_ordinal"].shift(59) == 59
    finite_factors = pd.Series(
        np.isfinite(frame.loc[:, list(ALPHAS)].to_numpy(dtype=float)).all(axis=1),
        index=frame.index,
    )
    eligible = frame.loc[
        (frame["session"] >= pd.Timestamp(protocol.research.start))
        & (frame["session"] <= pd.Timestamp(protocol.research.end))
        & (frame["listed_sessions"] >= protocol.research.minimum_listing_sessions)
        & frame["consecutive_60"]
        & ~frame["st"].astype(bool)
        & ~frame["suspended"].astype(bool)
        & (frame["mean_amount_20"] >= float(protocol.universe.minimum_mean_amount))
        & finite_factors
    ].copy()
    eligible["liquidity_rank"] = eligible.groupby("session", sort=True)["mean_amount_60"].rank(
        method="first", ascending=False
    )
    eligible = eligible.loc[eligible["liquidity_rank"] <= protocol.universe.size].copy()
    eligible["cross_section_size"] = eligible.groupby("session")["symbol"].transform("size")
    eligible = eligible.loc[
        eligible["cross_section_size"] >= protocol.universe.minimum_cross_section
    ].copy()
    standardized = eligible.groupby("session", sort=True, group_keys=False)[list(ALPHAS)].apply(
        _zscore
    )
    if isinstance(standardized.index, pd.MultiIndex):
        standardized.index = standardized.index.droplevel(0)
    eligible["score"] = standardized.mean(axis=1)
    eligible["score_rank"] = eligible.groupby("session", sort=True)["score"].rank(
        method="first", ascending=False
    )
    return eligible.loc[
        :,
        [
            "session",
            "symbol",
            "score",
            "score_rank",
            "liquidity_rank",
            "mean_amount_20",
            "cross_section_size",
            *ALPHAS,
        ],
    ].sort_values(["session", "score_rank", "symbol"], kind="stable")


def _rolling_beta5(values: pd.Series) -> pd.Series:
    x = np.arange(5, dtype=float)
    denominator = float(np.var(x, ddof=1))

    def calculate(window: np.ndarray) -> float:
        return -float(np.cov(x, window, ddof=1)[0, 1] / denominator / window[-1])

    return values.rolling(5, min_periods=5).apply(calculate, raw=True)


def _rolling_cntd5(values: pd.Series) -> pd.Series:
    def calculate(window: np.ndarray) -> float:
        return -float((window > 0).mean() - (window < 0).mean())

    return values.rolling(5, min_periods=5).apply(calculate, raw=True)


def _rolling_range20(group: pd.DataFrame) -> pd.Series:
    high = group["calc_high"].rolling(20, min_periods=20).apply(np.argmax, raw=True)
    low = group["calc_low"].rolling(20, min_periods=20).apply(np.argmin, raw=True)
    return -(high - low) / 20.0


def _zscore(frame: pd.DataFrame) -> pd.DataFrame:
    deviation = frame.std(axis=0, ddof=0).replace(0.0, np.nan)
    return frame.sub(frame.mean(axis=0), axis=1).div(deviation, axis=1).fillna(0.0)


def _require_columns(frame: pd.DataFrame, names: Sequence[str]) -> None:
    missing = set(names) - set(frame.columns)
    if missing:
        raise ValueError(f"historical bars lack columns: {', '.join(sorted(missing))}")
    if frame.empty:
        raise ValueError("historical bars are empty")
    if not pd.api.types.is_datetime64_any_dtype(frame["session"]):
        raise ValueError("historical sessions must be datetime64")
