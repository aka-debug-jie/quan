"""Pre-registered walk-forward splits without parameter selection or performance claims."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from hashlib import sha256
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


def verify_declared_config_hashes(config: dict[str, object], repository_root: Path) -> None:
    """Verify every immutable experiment input has the exact preregistered content hash."""
    declared = config.get("frozen_config_sha256")
    if not isinstance(declared, dict) or not declared:
        raise ValueError("experiment must declare frozen config hashes")
    for relative_path, expected_hash in declared.items():
        if not isinstance(relative_path, str) or not isinstance(expected_hash, str):
            raise ValueError("frozen config hashes must map paths to SHA-256 strings")
        observed_hash = sha256((repository_root / relative_path).read_bytes()).hexdigest()
        if observed_hash != expected_hash:
            raise ValueError(f"frozen config hash mismatch: {relative_path}")
