"""Frozen primary benchmark target generation, independent from strategy signals."""

from __future__ import annotations

from collections.abc import Iterable
from decimal import Decimal

import pandas as pd


def natural_month_end_sessions(index: pd.DatetimeIndex) -> tuple[pd.Timestamp, ...]:
    """Return the final observed valid session of every natural month in ascending order."""
    if not index.is_monotonic_increasing or not index.is_unique:
        raise ValueError("sessions must be unique and ascending")
    return tuple(index.to_series().groupby(index.to_period("M")).last())


def same_universe_equal_weight_targets(
    sessions: Iterable[pd.Timestamp], symbols: tuple[str, ...]
) -> dict[pd.Timestamp, dict[str, Decimal]]:
    """Create monthly equal-weight targets without trend, momentum, or tactical cash rules."""
    if not symbols or len(set(symbols)) != len(symbols):
        raise ValueError("benchmark requires a non-empty unique universe")
    weight = Decimal("1") / Decimal(len(symbols))
    target = {symbol: weight for symbol in symbols}
    target["CASH"] = Decimal("0")
    return {session: target.copy() for session in sessions}
