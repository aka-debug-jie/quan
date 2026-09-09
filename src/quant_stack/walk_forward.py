"""Pre-registered walk-forward splits without parameter selection or performance claims."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date


@dataclass(frozen=True)
class WalkForwardSplit:
    """One chronological train/test partition with no overlapping evaluation interval."""

    train_start: date
    train_end: date
    test_start: date
    test_end: date


def chronological_splits(
    dates: list[date], train_size: int, test_size: int
) -> list[WalkForwardSplit]:
    """Generate consecutive non-overlapping train/test windows from ascending dates."""
    if train_size <= 0 or test_size <= 0 or dates != sorted(dates) or len(set(dates)) != len(dates):
        raise ValueError("dates must be unique ascending and window sizes positive")
    splits: list[WalkForwardSplit] = []
    start = 0
    while start + train_size + test_size <= len(dates):
        splits.append(
            WalkForwardSplit(
                dates[start],
                dates[start + train_size - 1],
                dates[start + train_size],
                dates[start + train_size + test_size - 1],
            )
        )
        start += test_size
    return splits
