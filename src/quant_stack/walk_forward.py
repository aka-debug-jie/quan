"""Pre-registered walk-forward splits without parameter selection or performance claims."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from pathlib import Path

import yaml


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


def load_preregistered_experiment(path: Path) -> dict[str, object]:
    """Load a frozen experiment record and reject anything not explicitly preregistered."""
    payload = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict) or payload.get("status") != "preregistered_not_executed":
        raise ValueError("experiment must be a preregistered, not-yet-executed mapping")
    return payload


def require_executable_experiment(config: dict[str, object], snapshot_id: str) -> None:
    """Reject execution unless a frozen config and immutable input snapshot are named."""
    if config.get("status") != "preregistered_not_executed" or not snapshot_id:
        raise ValueError(
            "walk-forward execution requires frozen config and non-empty snapshot identity"
        )
