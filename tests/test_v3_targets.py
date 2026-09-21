"""Target cadence and holding-buffer tests."""

from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal

import pandas as pd

from quant_stack_v3.protocol import StrategySpec
from quant_stack_v3.targets import build_targets


def _scores() -> tuple[pd.DataFrame, tuple[date, ...]]:
    sessions = tuple(date(2020, 1, 2) + timedelta(days=index) for index in range(5))
    rows = []
    for session_index, session in enumerate(sessions):
        symbols = [f"sh{600000 + index:06d}" for index in range(25)]
        if session_index:
            symbols = [*symbols[1:], symbols[0]]
        for rank, symbol in enumerate(symbols, 1):
            rows.append(
                {
                    "session": pd.Timestamp(session),
                    "symbol": symbol,
                    "score_rank": rank,
                    "liquidity_rank": rank,
                    "mean_amount_20": 20_000_000,
                }
            )
    return pd.DataFrame(rows), sessions


def test_buffer_retains_incumbent_inside_exit_rank() -> None:
    scores, sessions = _scores()
    strategy = StrategySpec(id="A02_AF7_D1_B40", kind="af7", rebalance_sessions=1, exit_rank=40)
    targets = build_targets(
        scores,
        sessions,
        strategy,
        selection_count=20,
        liquidity_fraction=Decimal("0.01"),
    )
    assert len(targets) == 5
    assert targets[0].symbols == targets[1].symbols
    assert sum(targets[0].weights.values()) == Decimal("1")


def test_five_session_cadence_does_not_relabel_holding_horizon() -> None:
    scores, sessions = _scores()
    strategy = StrategySpec(id="A03_AF7_D5", kind="af7", rebalance_sessions=5, exit_rank=20)
    targets = build_targets(
        scores,
        sessions,
        strategy,
        selection_count=20,
        liquidity_fraction=Decimal("0.01"),
    )
    assert [item.signal_date for item in targets] == [sessions[0]]
