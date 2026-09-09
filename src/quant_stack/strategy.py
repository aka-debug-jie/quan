"""Frozen composition of point-in-time features and constrained portfolio construction."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import date
from decimal import Decimal

import pandas as pd

from quant_stack.benchmarks import natural_month_end_sessions
from quant_stack.features import FeatureRow
from quant_stack.portfolio import PortfolioConstraints, construct_weights


def etf_momentum_weights(rows: list[FeatureRow]) -> dict[str, Decimal]:
    """Return deterministic long-only weights from one same-date feature snapshot."""
    if not rows:
        return {"CASH": Decimal("1")}
    if len({row.bar.trading_date for row in rows}) != 1:
        raise ValueError("strategy requires one exchange-local feature date")
    return construct_weights(rows, PortfolioConstraints(Decimal("0.5"), Decimal("0.1"), 2))


def monthly_etf_momentum_targets(
    sessions: pd.DatetimeIndex, features_by_date: Mapping[date, list[FeatureRow]]
) -> dict[pd.Timestamp, dict[str, Decimal]]:
    """Calculate frozen targets only after each natural month's final supplied close."""
    targets: dict[pd.Timestamp, dict[str, Decimal]] = {}
    for session in natural_month_end_sessions(sessions):
        rows = features_by_date.get(session.date())
        if rows is None:
            raise ValueError("every month-end session requires a complete PIT feature snapshot")
        targets[session] = etf_momentum_weights(rows)
    return targets
