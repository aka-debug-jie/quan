"""Cross-provider comparison that reports disagreement without joining provider series."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from hashlib import sha256
from pathlib import Path

from quant_stack.data.models import ProviderId, ProviderSeriesManifest
from quant_stack.models import DailyBar
from quant_stack.snapshot import write_immutable

RECONCILIATION_VERSION = "2.0.0"


@dataclass(frozen=True)
class ReconciliationReport:
    """An immutable comparison outcome; it never selects or merges provider observations."""

    report_id: str
    status: str
    source_manifest_id: str
    cross_check_manifest_id: str | None
    adjudicator_manifest_id: str | None
    overlap_sessions: int
    mismatched_sessions: int
    adjudicated_sessions: int
    source_rejected_sessions: int
    unexplained_mismatches: int
    source_to_cross_check_volume_multiplier: str | None
    cross_check_volume_tolerance: str | None
    mismatch_dates: tuple[date, ...]
    maximum_price_absolute_difference: str | None
    maximum_price_relative_difference: str | None
    corporate_action_boundary_mismatches: int
    reasons: tuple[str, ...]

    def as_dict(self) -> dict[str, object]:
        """Return a stable JSON-ready report representation."""
        return {
            "report_id": self.report_id,
            "version": RECONCILIATION_VERSION,
            "status": self.status,
            "source_manifest_id": self.source_manifest_id,
            "cross_check_manifest_id": self.cross_check_manifest_id,
            "adjudicator_manifest_id": self.adjudicator_manifest_id,
            "overlap_sessions": self.overlap_sessions,
            "mismatched_sessions": self.mismatched_sessions,
            "adjudicated_sessions": self.adjudicated_sessions,
            "source_rejected_sessions": self.source_rejected_sessions,
            "unexplained_mismatches": self.unexplained_mismatches,
            "source_to_cross_check_volume_multiplier": self.source_to_cross_check_volume_multiplier,
            "cross_check_volume_tolerance": self.cross_check_volume_tolerance,
            "mismatch_dates": [value.isoformat() for value in self.mismatch_dates],
            "maximum_price_absolute_difference": self.maximum_price_absolute_difference,
            "maximum_price_relative_difference": self.maximum_price_relative_difference,
            "corporate_action_boundary_mismatches": self.corporate_action_boundary_mismatches,
            "reasons": list(self.reasons),
        }


def reconcile_raw_series(
    source_manifest: ProviderSeriesManifest,
    source_bars: list[DailyBar],
    cross_check_manifest: ProviderSeriesManifest | None,
    cross_check_bars: list[DailyBar] | None,
    corporate_action_boundary_dates: tuple[date, ...] = (),
    adjudicator_manifest: ProviderSeriesManifest | None = None,
    adjudicator_bars: list[DailyBar] | None = None,
) -> ReconciliationReport:
    """Compare full OHLCV records only on common dates; do not fill or concatenate gaps."""
    reasons: list[str] = []
    overlap = 0
    mismatches = 0
    adjudicated = 0
    source_rejected = 0
    unexplained = 0
    volume_multiplier: Decimal | None = None
    volume_tolerance: Decimal | None = None
    mismatch_dates: list[date] = []
    maximum_price_absolute_difference: Decimal | None = None
    maximum_price_relative_difference: Decimal | None = None
    boundary_mismatches = 0
    if cross_check_manifest is None or cross_check_bars is None:
        reasons.append("no independently captured cross-check provider series is available")
    else:
        if source_manifest.instrument != cross_check_manifest.instrument:
            raise ValueError("cross-provider reconciliation requires the same instrument")
        if source_manifest.provider is cross_check_manifest.provider:
            raise ValueError("cross-provider reconciliation requires independent providers")
        if source_manifest.price_basis != cross_check_manifest.price_basis:
            raise ValueError("cross-provider reconciliation requires the same price basis")
        adjudicator_by_date: dict[date, DailyBar] = {}
        if adjudicator_manifest is not None or adjudicator_bars is not None:
            if adjudicator_manifest is None or adjudicator_bars is None:
                raise ValueError("adjudicator manifest and bars must be supplied together")
            if adjudicator_manifest.instrument != source_manifest.instrument:
                raise ValueError("adjudicator requires the same instrument")
            if adjudicator_manifest.price_basis != source_manifest.price_basis:
                raise ValueError("adjudicator requires the same price basis")
            if adjudicator_manifest.provider in {
                source_manifest.provider,
                cross_check_manifest.provider,
            }:
                raise ValueError("adjudicator requires a third independent provider")
            adjudicator_by_date = {bar.trading_date: bar for bar in adjudicator_bars}
        volume_multiplier = _volume_multiplier(source_manifest, cross_check_manifest)
        volume_tolerance = _volume_tolerance(source_manifest, cross_check_manifest)
        if volume_multiplier is None:
            reasons.append("provider volume units have no configured deterministic conversion")
        right = {bar.trading_date: bar for bar in cross_check_bars}
        for left in source_bars:
            other = right.get(left.trading_date)
            if other is None:
                continue
            overlap += 1
            price_difference = _price_difference(left, other)
            volume_mismatch = (
                volume_multiplier is None
                or volume_tolerance is None
                or abs(left.volume * volume_multiplier - other.volume) > volume_tolerance
            )
            if price_difference is not None or volume_mismatch:
                mismatches += 1
                mismatch_dates.append(left.trading_date)
                if left.trading_date in corporate_action_boundary_dates:
                    boundary_mismatches += 1
                adjudicator = adjudicator_by_date.get(left.trading_date)
                if price_difference is not None and adjudicator is not None:
                    source_matches = _price_difference(left, adjudicator) is None
                    cross_check_matches = _price_difference(other, adjudicator) is None
                    if source_matches and not cross_check_matches and not volume_mismatch:
                        adjudicated += 1
                    elif cross_check_matches and not source_matches:
                        source_rejected += 1
                    else:
                        unexplained += 1
                else:
                    unexplained += 1
            if price_difference is not None:
                absolute, relative = price_difference
                maximum_price_absolute_difference = max(
                    maximum_price_absolute_difference or Decimal("0"), absolute
                )
                maximum_price_relative_difference = max(
                    maximum_price_relative_difference or Decimal("0"), relative
                )
        if overlap == 0:
            reasons.append("provider series have no common session for reconciliation")
        if source_rejected:
            reasons.append("official adjudicator rejects one or more source records")
        if unexplained:
            reasons.append("one or more overlapping OHLCV disagreements remain unexplained")
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
        "adjudicator_manifest_id": (
            adjudicator_manifest.manifest_id if adjudicator_manifest is not None else None
        ),
        "overlap_sessions": overlap,
        "mismatched_sessions": mismatches,
        "adjudicated_sessions": adjudicated,
        "source_rejected_sessions": source_rejected,
        "unexplained_mismatches": unexplained,
        "source_to_cross_check_volume_multiplier": (
            str(volume_multiplier) if volume_multiplier is not None else None
        ),
        "cross_check_volume_tolerance": (
            str(volume_tolerance) if volume_tolerance is not None else None
        ),
        "mismatch_dates": [value.isoformat() for value in mismatch_dates],
        "maximum_price_absolute_difference": (
            str(maximum_price_absolute_difference)
            if maximum_price_absolute_difference is not None
            else None
        ),
        "maximum_price_relative_difference": (
            str(maximum_price_relative_difference)
            if maximum_price_relative_difference is not None
            else None
        ),
        "corporate_action_boundary_mismatches": boundary_mismatches,
        "reasons": reasons,
    }
    return ReconciliationReport(
        report_id=_sha256(_canonical_json(payload)),
        status=status,
        source_manifest_id=source_manifest.manifest_id,
        cross_check_manifest_id=(
            cross_check_manifest.manifest_id if cross_check_manifest is not None else None
        ),
        adjudicator_manifest_id=(
            adjudicator_manifest.manifest_id if adjudicator_manifest is not None else None
        ),
        overlap_sessions=overlap,
        mismatched_sessions=mismatches,
        adjudicated_sessions=adjudicated,
        source_rejected_sessions=source_rejected,
        unexplained_mismatches=unexplained,
        source_to_cross_check_volume_multiplier=(
            str(volume_multiplier) if volume_multiplier is not None else None
        ),
        cross_check_volume_tolerance=(
            str(volume_tolerance) if volume_tolerance is not None else None
        ),
        mismatch_dates=tuple(mismatch_dates),
        maximum_price_absolute_difference=(
            str(maximum_price_absolute_difference)
            if maximum_price_absolute_difference is not None
            else None
        ),
        maximum_price_relative_difference=(
            str(maximum_price_relative_difference)
            if maximum_price_relative_difference is not None
            else None
        ),
        corporate_action_boundary_mismatches=boundary_mismatches,
        reasons=tuple(reasons),
    )


def persist_reconciliation_report(report: ReconciliationReport, data_root: Path) -> Path:
    """Write an immutable report separate from all provider-native and canonical series."""
    path = data_root / "reports" / "reconciliation" / f"{report.report_id}.json"
    write_immutable(path, _canonical_json(report.as_dict()) + b"\n")
    return path


def _price_tuple(bar: DailyBar) -> tuple[Decimal, Decimal, Decimal, Decimal]:
    """Return comparable raw price fields without silently converting a provider volume."""
    return (bar.open, bar.high, bar.low, bar.close)


def _price_difference(left: DailyBar, right: DailyBar) -> tuple[Decimal, Decimal] | None:
    """Return maximal absolute and relative OHLC difference, or None for an exact match."""
    differences = [
        abs(first - second)
        for first, second in zip(_price_tuple(left), _price_tuple(right), strict=True)
    ]
    maximum = max(differences)
    if maximum == 0:
        return None
    reference = min(value for value in (*_price_tuple(left), *_price_tuple(right)) if value > 0)
    return maximum, maximum / reference


def _volume_multiplier(
    source_manifest: ProviderSeriesManifest,
    cross_check_manifest: ProviderSeriesManifest,
) -> Decimal | None:
    """Return the only known shares-to-lots conversion; unknown units block reconciliation."""
    if source_manifest.volume_unit == cross_check_manifest.volume_unit:
        return Decimal("1")
    if source_manifest.volume_unit == "shares" and cross_check_manifest.volume_unit == "lots":
        return Decimal("0.01")
    if source_manifest.volume_unit == "lots" and cross_check_manifest.volume_unit == "shares":
        return Decimal("100")
    return None


def _volume_tolerance(
    source_manifest: ProviderSeriesManifest,
    cross_check_manifest: ProviderSeriesManifest,
) -> Decimal | None:
    """Return half of one reporting unit only where a source explicitly rounds 100-share lots."""
    if source_manifest.volume_unit == cross_check_manifest.volume_unit:
        return Decimal("0")
    if source_manifest.volume_unit == "shares" and cross_check_manifest.volume_unit == "lots":
        if cross_check_manifest.provider is ProviderId.AKSHARE_EASTMONEY:
            return Decimal("2")
        return Decimal("0.5")
    if source_manifest.volume_unit == "lots" and cross_check_manifest.volume_unit == "shares":
        if source_manifest.provider is ProviderId.AKSHARE_EASTMONEY:
            return Decimal("200")
        return Decimal("50")
    return None


def _canonical_json(value: object) -> bytes:
    """Encode report content deterministically for IDs and immutable output."""
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode(
        "utf-8"
    )


def _sha256(content: bytes) -> str:
    """Return a lowercase SHA-256 digest."""
    return sha256(content).hexdigest()
