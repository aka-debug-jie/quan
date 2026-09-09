"""Offline data validation routines."""

from __future__ import annotations

import csv
from collections.abc import Iterable
from pathlib import Path

from quant_stack.models import DailyBar


def reject_duplicate_bars(bars: Iterable[DailyBar]) -> None:
    """Reject repeated symbol and trading-date keys."""
    seen: set[tuple[str, object]] = set()
    for bar in bars:
        key = (bar.symbol, bar.trading_date)
        if key in seen:
            raise ValueError(f"duplicate bar: {bar.symbol} {bar.trading_date.isoformat()}")
        seen.add(key)


def load_daily_bars_csv(path: Path) -> list[DailyBar]:
    """Load and validate the stable M0 CSV schema without network access."""
    with path.open(newline="", encoding="utf-8") as handle:
        bars = [DailyBar.model_validate(row) for row in csv.DictReader(handle)]
    reject_duplicate_bars(bars)
    return bars
