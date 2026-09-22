"""Synthetic formula, chronology, and stable-ranking checks for upgrade signals."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest
from pandas.testing import assert_frame_equal

from quant_stack_v3.upgrade_signals import (
    EXPOSURES,
    UPGRADE_SIGNALS,
    build_upgrade_signals,
    residualize_scores,
)


def _bars(symbols: int = 100, periods: int = 90) -> pd.DataFrame:
    sessions = pd.bdate_range("2020-01-01", periods=periods)
    rows: list[dict[str, object]] = []
    for index in range(symbols):
        returns = 0.008 * np.sin(np.arange(periods) / 3) * (1 + index / 100) + index * 0.00001
        prices = 10 * np.exp(np.cumsum(returns))
        for ordinal, session in enumerate(sessions):
            rows.append(
                {
                    "session": session,
                    "symbol": f"s{index:03}",
                    "session_ordinal": ordinal,
                    "calc_close": prices[ordinal],
                    "amount": 1_000_000 + index * 1000 + ordinal * 10,
                }
            )
    return pd.DataFrame(rows)


def test_exact_trailing_formulas_and_market_proxy_beta() -> None:
    bars = _bars()
    result = build_upgrade_signals(bars, bars[["session", "symbol"]])
    day = result.loc[result.session.eq(result.session.max())].set_index("symbol")
    stock = bars.loc[bars.symbol.eq("s030")]
    prices = stock.calc_close.to_numpy()
    returns = np.log(prices[1:] / prices[:-1])[-60:]
    assert day.loc["s030", "MOM_60_5"] == pytest.approx(np.log(prices[-6] / prices[-61]))
    assert day.loc["s030", "DOWNSIDE_60"] == pytest.approx(
        -np.sqrt(np.mean(np.minimum(returns, 0) ** 2) * 252)
    )
    assert day.loc["s030", "vol60"] == pytest.approx(np.sqrt(np.mean(returns**2) * 252))
    assert day.loc["s030", "log_amount60"] == pytest.approx(np.log(stock.amount.iloc[-60:].mean()))
    proxy = result.groupby("session").return_1.mean().to_numpy()[-60:]
    assert day.loc["s030", "beta60"] == pytest.approx(
        np.cov(returns, proxy)[0, 1] / np.var(proxy, ddof=1)
    )
    expected = (day.MOM_60_5 - day.MOM_60_5.mean()) / day.MOM_60_5.std(ddof=0) / 2
    expected += (day.DOWNSIDE_60 - day.DOWNSIDE_60.mean()) / day.DOWNSIDE_60.std(ddof=0) / 2
    np.testing.assert_allclose(day.ROBUST_TREND, expected)


def test_prefix_and_future_mutations_do_not_change_past_or_inputs() -> None:
    bars = _bars()
    original = bars.copy(deep=True)
    eligible = bars[["session", "symbol"]].copy()
    cutoff = bars.session.sort_values().unique()[75]
    full = build_upgrade_signals(bars, eligible)
    prefix = build_upgrade_signals(
        bars.loc[bars.session.le(cutoff)], eligible.loc[eligible.session.le(cutoff)]
    )
    assert_frame_equal(full.loc[full.session.le(cutoff)].reset_index(drop=True), prefix)
    changed = bars.copy()
    changed.loc[changed.session.gt(cutoff), "calc_close"] *= 100
    changed.loc[changed.session.gt(cutoff), "amount"] *= 1000
    altered = build_upgrade_signals(changed, eligible)
    assert_frame_equal(full.loc[full.session.le(cutoff)], altered.loc[altered.session.le(cutoff)])
    assert_frame_equal(bars, original)
    residuals = residualize_scores(full, "MOM_60_5_score")
    prefix_residuals = residualize_scores(prefix, "MOM_60_5_score")
    assert_frame_equal(
        residuals.loc[residuals.session.le(cutoff)].reset_index(drop=True),
        prefix_residuals.reset_index(drop=True),
    )


def test_missing_session_invalidates_full_signal_day_and_beta_window() -> None:
    bars = _bars(periods=135)
    bars = bars.loc[~(bars.symbol.eq("s000") & bars.session_ordinal.eq(70))]
    result = build_upgrade_signals(bars, bars[["session", "symbol"]])
    affected = result.loc[result.session_ordinal.between(71, 130)]
    for signal in ("MOM_60_5", "DOWNSIDE_60", "ROBUST_TREND"):
        assert affected[signal].isna().all()
        assert affected[f"{signal}_rank"].isna().all()
    assert affected.loc[affected.symbol.eq("s000"), "beta60"].isna().all()
    recovered = result.loc[result.session_ordinal.eq(131)]
    assert recovered.MOM_60_5.notna().all()
    assert recovered.DOWNSIDE_60.notna().all()


def test_conditional_gate_excludes_candidates_and_enforces_50_rows() -> None:
    bars = _bars(symbols=200)
    # All amounts tied: only the volatility gate removes the highest-volatility quartile.
    bars["amount"] = 2_000_000
    result = build_upgrade_signals(bars, bars[["session", "symbol"]])
    last = result.loc[result.session.eq(result.session.max())]
    mask = last.vol20.le(last.vol20.quantile(0.75))
    assert last.loc[mask, "COND_REV_5_score"].notna().all()
    assert last.loc[~mask, "COND_REV_5"].isna().all()
    assert last.loc[~mask, "COND_REV_5_rank"].isna().all()
    selected = last.loc[mask].iloc[0]
    prices = bars.loc[bars.symbol.eq(selected.symbol), "calc_close"].to_numpy()
    assert selected.COND_REV_5 == pytest.approx(-np.log(prices[-1] / prices[-6]))
    # Increasing amounts retain only indices 100..149 after the volatility gate.
    bars["amount"] = bars.symbol.str[1:].astype(int) + 1_000_000
    gated = build_upgrade_signals(bars, bars[["session", "symbol"]])
    last_gated = gated.loc[gated.session.eq(gated.session.max())]
    assert last_gated.COND_REV_5.notna().sum() == 50
    small = bars.loc[bars.symbol.lt("s100")]
    small_result = build_upgrade_signals(small, small[["session", "symbol"]])
    assert small_result.COND_REV_5.isna().all()


def test_symbol_ties_and_input_order_are_deterministic() -> None:
    bars = _bars()
    prices = bars.loc[bars.symbol.eq("s000"), "calc_close"].to_numpy()
    bars["calc_close"] = np.tile(prices, 100)
    bars["amount"] = 1_000_000
    shuffled = bars.sample(frac=1, random_state=7)
    result = build_upgrade_signals(bars, bars[["session", "symbol"]])
    actual = build_upgrade_signals(shuffled, shuffled[["session", "symbol"]])
    assert_frame_equal(result, actual)
    last = result.loc[result.session.eq(result.session.max())]
    for signal in UPGRADE_SIGNALS:
        assert last[f"{signal}_score"].eq(0).all()
        assert last[f"{signal}_rank"].tolist() == list(range(1, 101))


def test_residuals_are_orthogonal_rank_deficiency_and_minimum_size() -> None:
    count = 70
    x = np.linspace(-1, 1, count)
    scores = pd.DataFrame(
        {
            "session": pd.Timestamp("2020-01-01"),
            "symbol": [f"s{index:03}" for index in range(count)],
            "score": x**2 + 3 * x,
            "beta60": x,
            "vol60": 2 * x,
            "log_amount60": 1.0,
        }
    )
    original = scores.copy(deep=True)
    actual = residualize_scores(scores.sample(frac=1, random_state=4))
    residual = actual.set_index("symbol").sort_index().residual_score.to_numpy()
    assert abs(residual.sum()) < 1e-12
    assert abs(residual @ x) < 1e-12
    assert_frame_equal(scores, original)
    assert residualize_scores(scores.iloc[:49]).empty
    scores.loc[0, "beta60"] = np.nan
    assert len(residualize_scores(scores.iloc[:50])) == 0
    assert len(residualize_scores(scores.iloc[:51])) == 50
    scores.loc[:, ["score", *EXPOSURES]] = 1.0
    ties = residualize_scores(scores.sample(frac=1, random_state=5))
    assert ties.symbol.tolist() == sorted(scores.symbol)
    assert ties.residual_rank.tolist() == list(range(1, 71))
