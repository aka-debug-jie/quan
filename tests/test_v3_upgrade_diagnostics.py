"""Hand-calculated tests for fixed pools and prior-close turnover accounting."""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import numpy as np
import pandas as pd
import pytest

from quant_stack.models import Side
from quant_stack_v3.fast_engine import HistoricalFill, HistoricalSnapshot
from quant_stack_v3.upgrade_diagnostics import summarize_fixed_pools, summarize_turnover_costs


def _scores(size: int = 50) -> pd.DataFrame:
    return pd.DataFrame(
        {
            "session": [date(2020, 1, 2)] * size,
            "symbol": [f"stock{rank:02}" for rank in range(1, size + 1)],
            "score_rank": range(1, size + 1),
            "score": list(reversed(range(size))),
        }
    )


def test_missing_labels_do_not_replace_fixed_top_or_bottom_members() -> None:
    scores = _scores()
    labels = scores.loc[:, ["session", "symbol"]].copy()
    labels["forward"] = scores.score_rank / 100
    labels = labels.loc[~labels.symbol.isin(["stock01", "stock50"])]
    before_scores = scores.copy(deep=True)
    before_labels = labels.copy(deep=True)
    row = summarize_fixed_pools(scores.sample(frac=1, random_state=7), labels, "forward").iloc[0]
    assert row.top_symbols == tuple(f"stock{rank:02}" for rank in range(1, 21))
    assert row.bottom_symbols == tuple(f"stock{rank:02}" for rank in range(31, 51))
    assert row.top_label_count == row.bottom_label_count == 19
    assert row.pool_label_count == 48
    assert row.top_coverage == row.bottom_coverage == 0.95
    assert row.pool_coverage == 0.96
    assert row.top_mean == pytest.approx(0.11)
    assert row.bottom_mean == pytest.approx(0.40)
    assert row.pool_mean == pytest.approx(0.255)
    assert row.top_minus_pool == pytest.approx(-0.145)
    assert row.pool_minus_bottom == pytest.approx(-0.145)
    assert row.top_minus_bottom == pytest.approx(-0.29)
    assert row.legacy_bottom_label_count == 21  # Old threshold is rank > 48 - 20.
    assert row.legacy_top_minus_bottom == pytest.approx(0.11 - 0.39)
    assert row.fixed_minus_legacy_spread == pytest.approx(-0.01)
    pd.testing.assert_frame_equal(scores, before_scores)
    pd.testing.assert_frame_equal(labels, before_labels)


def test_complete_labels_match_legacy_spread() -> None:
    scores = _scores()
    labels = scores.loc[:, ["session", "symbol"]].copy()
    labels["forward"] = scores.score_rank / 100
    row = summarize_fixed_pools(scores, labels, "forward").iloc[0]
    assert row.top_minus_bottom == pytest.approx(-0.30)
    assert row.fixed_minus_legacy_spread == pytest.approx(0)
    assert row.overlapping_members == 0


def test_entirely_missing_group_stays_missing_and_small_pools_expose_overlap() -> None:
    scores = _scores(30)
    labels = scores.loc[:, ["session", "symbol"]].copy()
    labels["forward"] = np.inf
    row = summarize_fixed_pools(scores, labels, "forward").iloc[0]
    assert row.top_size == row.bottom_size == 20
    assert row.overlapping_members == 10
    assert row.pool_coverage == row.top_coverage == row.bottom_coverage == 0
    assert np.isnan(row.top_minus_bottom)
    assert np.isnan(row.legacy_top_minus_bottom)


def _snapshot(session: date, nav: str) -> HistoricalSnapshot:
    return HistoricalSnapshot(session, Decimal(nav), {}, Decimal(nav), Decimal(0), Decimal(0))


def _fill(session: date, side: Side, notional: str) -> HistoricalFill:
    return HistoricalFill(
        "order",
        session,
        "stock",
        side,
        Decimal(1),
        Decimal(notional),
        Decimal(notional),
        Decimal(notional),
        Decimal(1),
        Decimal(2),
        Decimal(3),
        Decimal(4),
        Decimal(5),
    )


def test_turnover_uses_previous_close_and_counts_zero_trade_days() -> None:
    first, second, third = date(2020, 12, 30), date(2020, 12, 31), date(2021, 1, 4)
    snapshots = [_snapshot(first, "200"), _snapshot(second, "400"), _snapshot(third, "800")]
    fills = [_fill(first, Side.BUY, "50"), _fill(second, Side.SELL, "100")]
    report = summarize_turnover_costs(fills, snapshots, Decimal(100))
    assert [row.previous_close_nav for row in report.daily] == [100, 200, 400]
    assert [row.two_sided_turnover for row in report.daily] == [Decimal("0.5"), Decimal("0.5"), 0]
    assert report.total.gross_notional == 150
    assert report.total.buy_notional == 50
    assert report.total.sell_notional == 100
    assert report.total.two_sided_turnover == 1
    assert report.total.half_turnover == Decimal("0.5")
    assert report.total.mean_daily_two_sided_turnover == Decimal(1) / 3
    assert report.total.annualized_two_sided_turnover == (Decimal(1) / 3) * 252
    assert report.total.annualized_half_turnover == (Decimal(1) / 3) * 252 / 2
    assert report.total.total_cost == 30
    assert report.total.costs == dict(
        commission=2, spread_cost=4, slippage_cost=6, tax_cost=8, transfer_fee=10
    )
    assert report.total.cost_component_shares["commission"] == Decimal(2) / 30
    assert report.total.cost_to_gross_notional == Decimal("0.2")
    assert report.total.sum_cost_to_previous_nav == Decimal("0.225")
    assert report.total.mean_daily_cost_to_previous_nav == Decimal("0.075")
    assert report.daily[2].cost_to_gross_notional is None
    assert report.yearly["2020"].two_sided_turnover == 1
    assert report.yearly["2020"].mean_daily_two_sided_turnover == Decimal("0.5")
    assert report.yearly["2021"].two_sided_turnover == 0
    assert report.yearly["2021"].cost_component_shares["commission"] is None
    assert report.legacy_gross_notional_over_mean_close_nav == Decimal(150) / (Decimal(1400) / 3)


def test_buy_and_sell_same_session_and_no_fills() -> None:
    session = date(2020, 1, 2)
    snapshots = [_snapshot(session, "500")]
    report = summarize_turnover_costs(
        [_fill(session, Side.BUY, "100"), _fill(session, Side.SELL, "100")],
        snapshots,
        Decimal(1000),
    )
    assert report.total.two_sided_turnover == Decimal("0.2")
    assert report.total.half_turnover == Decimal("0.1")
    assert report.total.fill_count == 2
    empty = summarize_turnover_costs([], snapshots, Decimal(1000))
    assert empty.total.gross_notional == empty.total.total_cost == 0
    assert empty.total.cost_to_gross_notional is None


def test_turnover_rejects_missing_sessions_and_invalid_denominators() -> None:
    session = date(2020, 1, 2)
    snapshots = [_snapshot(session, "100")]
    with pytest.raises(ValueError, match="fill session"):
        summarize_turnover_costs([_fill(date(2020, 1, 3), Side.BUY, "10")], snapshots, Decimal(100))
    with pytest.raises(ValueError, match="unique, increasing"):
        summarize_turnover_costs([], snapshots * 2, Decimal(100))
    with pytest.raises(ValueError, match="positive initial"):
        summarize_turnover_costs([], snapshots, Decimal(0))
    with pytest.raises(ValueError, match="NAV must be positive"):
        summarize_turnover_costs([], [_snapshot(session, "0")], Decimal(100))
