"""Cross-provider comparison that reports disagreement without joining provider series."""

from __future__ import annotations

import json
from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path

from quant_stack.data.models import ProviderSeriesManifest
from quant_stack.models import DailyBar
from quant_stack.snapshot import write_immutable

RECONCILIATION_VERSION = "1.0.0"


@dataclass(frozen=True)
class ReconciliationReport:
    """An immutable comparison outcome; it never selects or merges provider observations."""

    report_id: str
    status: str
    source_manifest_id: str
    cross_check_manifest_id: str | None
    overlap_sessions: int
    mismatched_sessions: int
    reasons: tuple[str, ...]

    def as_dict(self) -> dict[str, object]:
        """Return a stable JSON-ready report representation."""
        return {
            "report_id": self.report_id,
            "version": RECONCILIATION_VERSION,
            "status": self.status,
            "source_manifest_id": self.source_manifest_id,
            "cross_check_manifest_id": self.cross_check_manifest_id,
            "overlap_sessions": self.overlap_sessions,
            "mismatched_sessions": self.mismatched_sessions,
            "reasons": list(self.reasons),
        }


def reconcile_raw_series(
    source_manifest: ProviderSeriesManifest,
    source_bars: list[DailyBar],
    cross_check_manifest: ProviderSeriesManifest | None,
    cross_check_bars: list[DailyBar] | None,
) -> ReconciliationReport:
    """Compare full OHLCV records only on common dates; do not fill or concatenate gaps."""
    reasons: list[str] = []
    overlap = 0
    mismatches = 0
    if cross_check_manifest is None or cross_check_bars is None:
        reasons.append("no independently captured cross-check provider series is available")
    else:
        if source_manifest.instrument != cross_check_manifest.instrument:
            raise ValueError("cross-provider reconciliation requires the same instrument")
        if source_manifest.price_basis != cross_check_manifest.price_basis:
            raise ValueError("cross-provider reconciliation requires the same price basis")
        right = {bar.trading_date: bar for bar in cross_check_bars}
        for left in source_bars:
            other = right.get(left.trading_date)
            if other is None:
                continue
            overlap += 1
            if _bar_tuple(left) != _bar_tuple(other):
                mismatches += 1
        if overlap == 0:
            reasons.append("provider series have no common session for reconciliation")
        if mismatches:
            reasons.append("one or more overlapping OHLCV records disagree")
    if source_manifest.row_count == 0:
        reasons.append("source provider series is empty")
    status = "pass" if not reasons else "blocked"
    payload = {
        "version": RECONCILIATION_VERSION,
        "status": status,
        "source_manifest_id": source_manifest.manifest_id,
        "cross_check_manifest_id": (
            cross_check_manifest.manifest_id if cross_check_manifest is not None else None
        ),
        "overlap_sessions": overlap,
        "mismatched_sessions": mismatches,
        "reasons": reasons,
    }
    return ReconciliationReport(
        report_id=_sha256(_canonical_json(payload)),
        status=status,
        source_manifest_id=source_manifest.manifest_id,
        cross_check_manifest_id=(
            cross_check_manifest.manifest_id if cross_check_manifest is not None else None
        ),
        overlap_sessions=overlap,
        mismatched_sessions=mismatches,
        reasons=tuple(reasons),
    )


def persist_reconciliation_report(report: ReconciliationReport, data_root: Path) -> Path:
    """Write an immutable report separate from all provider-native and canonical series."""
    path = data_root / "reports" / "reconciliation" / f"{report.report_id}.json"
    write_immutable(path, _canonical_json(report.as_dict()) + b"\n")
    return path


def _bar_tuple(bar: DailyBar) -> tuple[object, ...]:
    """Return the comparable raw OHLCV fields for exactly one session."""
    return (bar.open, bar.high, bar.low, bar.close, bar.volume)


def _canonical_json(value: object) -> bytes:
    """Encode report content deterministically for IDs and immutable output."""
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode(
        "utf-8"
    )


def _sha256(content: bytes) -> str:
    """Return a lowercase SHA-256 digest."""
    return sha256(content).hexdigest()
