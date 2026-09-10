"""Frozen-universe data qualification before any locked research evaluation."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from datetime import date
from hashlib import sha256
from itertools import pairwise
from pathlib import Path

import pyarrow.parquet as pq  # type: ignore[import-untyped]

from quant_stack.d0_inventory import (
    D0EventInventoryReport,
    build_event_inventory,
    load_d0_source_registry,
    persist_event_inventory,
)
from quant_stack.data.calendar import CalendarSourceError, ExchangeCalendarStore
from quant_stack.data.canonical import CANONICAL_ALGORITHM_VERSION
from quant_stack.data.corporate_actions import load_corporate_action_ledger
from quant_stack.data.evidence import EvidenceArchiveError, require_corporate_action_evidence
from quant_stack.data.ingest import load_etf_universe
from quant_stack.data.models import ETFUniverseInstrument
from quant_stack.data.provider_series import load_provider_series
from quant_stack.models import DailyBar, PriceBasis
from quant_stack.research_inputs import preflight_causal_universe
from quant_stack.snapshot import write_immutable


@dataclass(frozen=True)
class CandidateInventory:
    """Provider and raw-price diagnostics; neither is official corporate-action evidence."""

    provider_factor_change_points: int
    provider_factor_classification: str
    raw_discontinuity_dates: tuple[str, ...]
    unresolved_raw_discontinuity_dates: tuple[str, ...]
    unresolved_factor_change_points: int


@dataclass(frozen=True)
class AssetQualification:
    """One frozen-universe asset's conservative qualification state and evidence identifiers."""

    symbol: str
    exchange: str
    raw_coverage: bool
    expected_session_coverage: bool
    raw_manifest_id: str | None
    raw_manifest_sha256_valid: bool
    ledger_status: str
    ledger_sha256: str | None
    ledger_evidence_archived: bool
    inventory_complete: bool
    inventory_report_id: str
    official_event_count: int
    unresolved_official_events: int
    pit_causal_safe: bool
    causal_adjusted_available: bool
    causal_manifest_id: str | None
    execution_raw_available: bool
    cross_provider_reconciliation: bool
    cross_provider_report_id: str | None
    deterministic_reproduction: bool
    deterministic_reproduction_report_id: str | None
    candidate_inventory: CandidateInventory
    result: str
    reasons: tuple[str, ...]


@dataclass(frozen=True)
class UniverseDataQualificationReport:
    """A complete scan of the frozen universe, not a partial remediation result."""

    universe_sha256: str
    source_registry_sha256: str
    assets: tuple[AssetQualification, ...]

    @property
    def all_qualified(self) -> bool:
        """Return true only if every frozen asset is independently qualified."""
        return bool(self.assets) and all(asset.result == "QUALIFIED" for asset in self.assets)


def qualify_frozen_universe(
    universe_path: Path,
    data_root: Path,
    ledger_root: Path,
    calendar_root: Path = Path("configs/calendars"),
    artifact_root: Path = Path("artifacts/data_qualification"),
    source_registry_path: Path = Path("configs/data_qualification/d0_sources_v1.yaml"),
) -> UniverseDataQualificationReport:
    """Audit every frozen ETF asset without using provider qfq as canonical adjusted data."""
    universe = load_etf_universe(universe_path)
    if not universe.instruments:
        raise ValueError("frozen universe must contain instruments")
    registry = load_d0_source_registry(source_registry_path, universe_path)
    registry_sha256 = sha256(source_registry_path.read_bytes()).hexdigest()
    selections = {(item.symbol, item.exchange): item for item in registry.assets}
    universe_identities = {(item.symbol, item.exchange) for item in universe.instruments}
    if set(selections) != universe_identities:
        raise ValueError("D0 source registry must select every frozen-universe asset exactly once")
    causal_preflight = preflight_causal_universe(
        universe_path, data_root / "canonical" / "manifests", data_root
    )
    causal_by_identity = {(item.symbol, item.exchange): item for item in causal_preflight.inputs}
    assets: list[AssetQualification] = []
    calendar = ExchangeCalendarStore(calendar_root)
    for instrument in universe.instruments:
        symbol = instrument.symbol
        exchange = instrument.exchange.value
        selection = selections[(symbol, instrument.exchange)]
        raw_manifest = _manifest_payload_by_id(data_root, selection.canonical_raw_manifest_id)
        try:
            provider_manifest, raw_bars = load_provider_series(
                selection.canonical_raw_manifest_id, data_root
            )
        except ValueError:
            provider_manifest, raw_bars = None, []
        if provider_manifest is not None and (
            provider_manifest.instrument.symbol != symbol
            or provider_manifest.instrument.exchange != instrument.exchange
        ):
            raise ValueError("D0 canonical raw selection has the wrong instrument identity")
        ledger_path = ledger_root / f"{symbol}_v1.yaml"
        ledger_status, evidence_archived = _ledger_status(ledger_path, data_root)
        if ledger_path.is_file() and raw_bars:
            ledger = load_corporate_action_ledger(ledger_path)
            inventory_report = build_event_inventory(selection, ledger, raw_bars, data_root)
        else:
            inventory_report = D0EventInventoryReport(
                symbol=symbol,
                exchange=exchange,
                provider_candidate_sha256=selection.adjustment_candidate_sha256,
                official_inventory_complete=False,
                rows=(),
            )
        inventory_path = persist_event_inventory(
            inventory_report, artifact_root / "event_inventories"
        )
        inventory_report_id = inventory_path.parent.name
        official_event_count, unresolved_official_events = _official_event_inventory(ledger_path)
        ledger_sha256 = (
            sha256(ledger_path.read_bytes()).hexdigest() if ledger_path.is_file() else None
        )
        causal_input = causal_by_identity.get((symbol, exchange))
        if causal_input is not None and not _causal_manifest_uses_source(
            data_root, causal_input.manifest_id, selection.canonical_raw_manifest_id
        ):
            causal_input = None
        inventory = _candidate_inventory(inventory_report, raw_bars, ledger_path)
        reconciliation_report_id = _passing_reconciliation_report(
            data_root / "reports" / "reconciliation",
            selection.canonical_raw_manifest_id,
            selection.cross_check_manifest_id,
            selection.adjudicator_manifest_id,
            (
                provider_manifest.row_count
                if provider_manifest is not None and selection.reconciliation_scope == "full_source"
                else selection.minimum_overlap_sessions or 0
            ),
            selection.reconciliation_scope == "full_source",
        )
        cross_provider_reconciliation = reconciliation_report_id is not None
        expected_session_coverage = _expected_session_coverage(
            raw_manifest, instrument, data_root, calendar
        )
        raw_coverage = raw_manifest is not None and expected_session_coverage
        raw_valid = _manifest_files_match(raw_manifest, data_root)
        causal_available = causal_input is not None
        reproduction_report_id = _passing_reproduction_report(
            artifact_root / "reproductions",
            _string(raw_manifest, "manifest_id"),
            ledger_sha256,
            causal_input.manifest_id if causal_input else None,
            registry_sha256,
        )
        deterministic_reproduction = reproduction_report_id is not None
        pit_safe = ledger_status == "complete" and evidence_archived and causal_available
        reasons = _qualification_reasons(
            raw_coverage,
            expected_session_coverage,
            raw_valid,
            ledger_status,
            evidence_archived,
            inventory_report.inventory_complete,
            unresolved_official_events,
            causal_available,
            inventory,
            cross_provider_reconciliation,
            deterministic_reproduction,
        )
        assets.append(
            AssetQualification(
                symbol=symbol,
                exchange=exchange,
                raw_coverage=raw_coverage,
                expected_session_coverage=expected_session_coverage,
                raw_manifest_id=_string(raw_manifest, "manifest_id"),
                raw_manifest_sha256_valid=raw_valid,
                ledger_status=ledger_status,
                ledger_sha256=ledger_sha256,
                ledger_evidence_archived=evidence_archived,
                inventory_complete=inventory_report.inventory_complete,
                inventory_report_id=inventory_report_id,
                official_event_count=official_event_count,
                unresolved_official_events=unresolved_official_events,
                pit_causal_safe=pit_safe,
                causal_adjusted_available=causal_available,
                causal_manifest_id=causal_input.manifest_id if causal_input else None,
                execution_raw_available=raw_coverage and raw_valid,
                cross_provider_reconciliation=cross_provider_reconciliation,
                cross_provider_report_id=reconciliation_report_id,
                deterministic_reproduction=deterministic_reproduction,
                deterministic_reproduction_report_id=reproduction_report_id,
                candidate_inventory=inventory,
                result="QUALIFIED" if not reasons else "NOT_QUALIFIED",
                reasons=tuple(reasons),
            )
        )
    return UniverseDataQualificationReport(
        universe_sha256=sha256(universe_path.read_bytes()).hexdigest(),
        source_registry_sha256=registry_sha256,
        assets=tuple(assets),
    )


def persist_qualification_report(
    report: UniverseDataQualificationReport, artifact_root: Path
) -> Path:
    """Write a deterministic qualification artifact that cannot overwrite a different report."""
    payload = {
        "universe_sha256": report.universe_sha256,
        "source_registry_sha256": report.source_registry_sha256,
        "all_qualified": report.all_qualified,
        "assets": [asdict(asset) for asset in report.assets],
    }
    content = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode() + b"\n"
    report_id = sha256(content).hexdigest()
    destination = artifact_root / report_id / "qualification.json"
    write_immutable(destination, content)
    return destination


def _manifest_payload_by_id(data_root: Path, manifest_id: str) -> dict[str, object] | None:
    """Load exactly the provider manifest selected by the frozen D0 registry."""
    candidates = (
        data_root / "manifests" / f"{manifest_id}.json",
        data_root / "manifests" / "providers" / f"{manifest_id}.json",
    )
    path = next((item for item in candidates if item.is_file()), None)
    if path is None:
        return None
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("selected D0 provider manifest must be a JSON object")
    if payload.get("manifest_id") != manifest_id:
        raise ValueError("selected D0 provider manifest identity mismatch")
    return {str(key): value for key, value in payload.items()}


def _ledger_status(ledger_path: Path, data_root: Path) -> tuple[str, bool]:
    """Report verified ledger state; an absent or invalid ledger is never silently accepted."""
    if not ledger_path.is_file():
        return "missing", False
    try:
        ledger = load_corporate_action_ledger(ledger_path)
        require_corporate_action_evidence(ledger.events, data_root)
    except (EvidenceArchiveError, ValueError):
        return "invalid_or_unarchived", False
    return ledger.completeness, True


def _official_event_inventory(ledger_path: Path) -> tuple[int, int]:
    """Count total and still-candidate official-event inventory rows without promoting them."""
    if not ledger_path.is_file():
        return 0, 0
    try:
        ledger = load_corporate_action_ledger(ledger_path)
    except ValueError:
        return 0, 0
    return len(ledger.events), sum(
        event.verification_status == "candidate" for event in ledger.events
    )


def _candidate_inventory(
    event_report: D0EventInventoryReport, raw_bars: list[DailyBar], ledger_path: Path
) -> CandidateInventory:
    """Summarize event-level provider candidates and raw-price discontinuities."""
    factor_changes = sum(row.provider_factor_change for row in event_report.rows)
    discontinuities = tuple(
        current.trading_date.isoformat()
        for previous, current in pairwise(raw_bars)
        if abs(current.close / previous.close - 1) > 0.2
    )
    raw_dates = tuple(item.trading_date for item in raw_bars)
    action_dates = _applied_ledger_dates(ledger_path, raw_dates)
    unresolved_discontinuities = tuple(
        item for item in discontinuities if date.fromisoformat(item) not in action_dates
    )
    unresolved = event_report.unexplained_count
    classification = "EVENT_LEVEL_RECONCILED" if unresolved == 0 else "UNEXPLAINED"
    return CandidateInventory(
        factor_changes,
        classification,
        discontinuities,
        unresolved_discontinuities,
        unresolved,
    )


def _applied_ledger_dates(ledger_path: Path, raw_dates: tuple[date, ...]) -> set[date]:
    """Map configured official actions to their first available raw session for diagnostics."""
    if not ledger_path.is_file():
        return set()
    try:
        ledger = load_corporate_action_ledger(ledger_path)
    except ValueError:
        return set()
    applied: set[date] = set()
    for event in ledger.events:
        next_date = next((value for value in raw_dates if value >= event.effective_date), None)
        if next_date is not None:
            applied.add(next_date)
    return applied


def _expected_session_coverage(
    raw_manifest: dict[str, object] | None,
    instrument: ETFUniverseInstrument,
    data_root: Path,
    calendar: ExchangeCalendarStore,
) -> bool:
    """Recompute local-calendar coverage from retained raw bars and documented exceptions."""
    if raw_manifest is None:
        return False
    raw_path = _normalized_path(raw_manifest, data_root)
    if raw_path is None:
        return False
    bars = pq.read_table(raw_path, columns=["trading_date"]).to_pandas()
    if bars.empty:
        return False
    dates = {
        value if isinstance(value, date) else date.fromisoformat(str(value))
        for value in bars.trading_date
    }
    start = min(dates)
    end = max(dates)
    try:
        calendar.require_source_archives(instrument.exchange, start, end, data_root)
        coverage = calendar.coverage_report(
            instrument,
            PriceBasis.RAW,
            dates,
            start,
            end,
            documented_non_trading_events=instrument.documented_non_trading_events,
        )
    except (CalendarSourceError, ValueError):
        return False
    return coverage.is_complete


def _passing_reconciliation_report(
    report_root: Path,
    source_manifest_id: str | None,
    cross_check_manifest_id: str | None,
    adjudicator_manifest_id: str | None,
    required_overlap_sessions: int,
    require_exact_overlap: bool,
) -> str | None:
    """Return a retained zero-mismatch cross-provider report for the selected raw source."""
    if source_manifest_id is None or cross_check_manifest_id is None:
        return None
    for path in sorted(report_root.glob("*.json")):
        payload = json.loads(path.read_text(encoding="utf-8"))
        report_id = payload.get("report_id")
        identity_payload = dict(payload)
        identity_payload.pop("report_id", None)
        overlap = payload.get("overlap_sessions")
        overlap_satisfies = isinstance(overlap, int) and (
            overlap == required_overlap_sessions
            if require_exact_overlap
            else overlap >= required_overlap_sessions
        )
        if (
            isinstance(report_id, str)
            and path.stem == report_id
            and sha256(
                json.dumps(
                    identity_payload,
                    ensure_ascii=False,
                    sort_keys=True,
                    separators=(",", ":"),
                ).encode("utf-8")
            ).hexdigest()
            == report_id
            and payload.get("status") == "pass"
            and payload.get("source_manifest_id") == source_manifest_id
            and payload.get("cross_check_manifest_id") == cross_check_manifest_id
            and payload.get("adjudicator_manifest_id") == adjudicator_manifest_id
            and overlap_satisfies
            and payload.get("source_rejected_sessions", 0) == 0
            and payload.get("unexplained_mismatches", payload.get("mismatched_sessions")) == 0
        ):
            return report_id
    return None


def _passing_reproduction_report(
    report_root: Path,
    source_manifest_id: str | None,
    ledger_sha256: str | None,
    causal_manifest_id: str | None,
    source_registry_sha256: str,
) -> str | None:
    """Return an immutable exact-output causal reproduction report for the current inputs."""
    if source_manifest_id is None or ledger_sha256 is None or causal_manifest_id is None:
        return None
    for path in sorted(report_root.glob("*/causal_reproduction.json")):
        content = path.read_bytes()
        payload = json.loads(content)
        report_id = path.parent.name
        if (
            sha256(content).hexdigest() == report_id
            and payload.get("status") == "pass"
            and payload.get("source_manifest_id") == source_manifest_id
            and payload.get("ledger_sha256") == ledger_sha256
            and payload.get("source_registry_sha256") == source_registry_sha256
            and payload.get("adjustment_algorithm_version") == CANONICAL_ALGORITHM_VERSION
            and isinstance(payload.get("git_commit"), str)
            and bool(payload.get("git_commit"))
            and payload.get("expected_causal_manifest_id") == causal_manifest_id
            and payload.get("observed_causal_manifest_id") == causal_manifest_id
            and payload.get("expected_output_sha256") == payload.get("observed_output_sha256")
        ):
            return report_id
    return None


def _matching_qfq_manifest(
    manifest_root: Path, symbol: str, exchange: str
) -> dict[str, object] | None:
    """Find the latest complete provider qfq export only for discovery diagnostics."""
    candidates: list[dict[str, object]] = []
    for path in sorted(manifest_root.glob("*.json")):
        payload = json.loads(path.read_text(encoding="utf-8"))
        request = payload.get("request")
        if not isinstance(request, dict) or request.get("price_basis") != PriceBasis.QFQ.value:
            continue
        instrument = request.get("instrument")
        if (
            isinstance(instrument, dict)
            and instrument.get("symbol") == symbol
            and instrument.get("exchange") == exchange
            and payload.get("coverage_complete") is True
        ):
            candidates.append(payload)
    return (
        sorted(candidates, key=lambda item: str(item.get("first_captured_at", "")))[-1]
        if candidates
        else None
    )


def _causal_manifest_uses_source(
    data_root: Path, causal_manifest_id: str, source_manifest_id: str
) -> bool:
    """Bind an accepted causal output to the registry-selected raw source."""
    path = data_root / "canonical" / "manifests" / f"{causal_manifest_id}.json"
    if not path.is_file():
        return False
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        return False
    return bool(payload.get("source_manifest_ids") == [source_manifest_id])


def _manifest_files_match(manifest: dict[str, object] | None, data_root: Path) -> bool:
    """Verify retained raw and normalized hashes named by one provider manifest."""
    if manifest is None:
        return False
    files = (manifest.get("raw_file"), manifest.get("normalized_file"))
    for file_data in files:
        if not isinstance(file_data, dict):
            return False
        relative = file_data.get("relative_path")
        expected = file_data.get("sha256")
        if not isinstance(relative, str) or not isinstance(expected, str):
            return False
        path = data_root / relative
        if not path.is_file() or sha256(path.read_bytes()).hexdigest() != expected:
            return False
    return True


def _normalized_path(manifest: dict[str, object], data_root: Path) -> Path | None:
    """Resolve a validated normalized provider path from one manifest."""
    normalized = manifest.get("normalized_file")
    if not isinstance(normalized, dict) or not isinstance(normalized.get("relative_path"), str):
        return None
    path = data_root / normalized["relative_path"]
    return path if path.is_file() else None


def _request_identity(manifest: dict[str, object], field: str) -> str | None:
    """Extract one string instrument identity field from a provider manifest."""
    request = manifest.get("request")
    instrument = (
        request.get("instrument") if isinstance(request, dict) else manifest.get("instrument")
    )
    value = instrument.get(field) if isinstance(instrument, dict) else None
    return value if isinstance(value, str) else None


def _canonical_raw_available(data_root: Path, symbol: str, exchange: str) -> bool:
    """Verify a published canonical raw artifact for a provider-native raw source."""
    for path in (data_root / "canonical" / "manifests").glob("*.json"):
        payload = json.loads(path.read_text(encoding="utf-8"))
        instrument = payload.get("instrument")
        output = payload.get("output_file")
        if (
            payload.get("price_basis") != PriceBasis.RAW.value
            or not isinstance(instrument, dict)
            or not isinstance(output, dict)
            or instrument.get("symbol") != symbol
            or instrument.get("exchange") != exchange
        ):
            continue
        relative = output.get("relative_path")
        expected = output.get("sha256")
        if isinstance(relative, str) and isinstance(expected, str):
            output_path = data_root / relative
            if output_path.is_file() and sha256(output_path.read_bytes()).hexdigest() == expected:
                return True
    return False


def _string(payload: dict[str, object] | None, field: str) -> str | None:
    """Extract an optional string from a JSON mapping."""
    value = payload.get(field) if payload else None
    return value if isinstance(value, str) else None


def _qualification_reasons(
    raw_coverage: bool,
    expected_session_coverage: bool,
    raw_valid: bool,
    ledger_status: str,
    evidence_archived: bool,
    inventory_complete: bool,
    unresolved_official_events: int,
    causal_available: bool,
    inventory: CandidateInventory,
    cross_provider_reconciliation: bool,
    deterministic_reproduction: bool,
) -> list[str]:
    """List every unmet D0 gate without converting missing evidence into a pass."""
    reasons: list[str] = []
    if not raw_coverage:
        reasons.append("raw_coverage_missing")
    if not expected_session_coverage:
        reasons.append("expected_session_coverage_unverified")
    if not raw_valid:
        reasons.append("raw_manifest_hash_invalid")
    if ledger_status != "complete":
        reasons.append("corporate_action_ledger_not_complete")
    if not evidence_archived:
        reasons.append("corporate_action_evidence_not_archived")
    if not inventory_complete:
        reasons.append("official_event_inventory_not_complete")
    if unresolved_official_events:
        reasons.append("unresolved_official_events")
    if not causal_available:
        reasons.append("canonical_causal_adjusted_missing")
    if inventory.unresolved_factor_change_points:
        reasons.append("unresolved_provider_factor_change_points")
    if inventory.unresolved_raw_discontinuity_dates:
        reasons.append("unresolved_raw_price_discontinuities")
    if not cross_provider_reconciliation:
        reasons.append("cross_provider_reconciliation_unverified")
    if not deterministic_reproduction:
        reasons.append("deterministic_reproduction_unverified")
    return reasons
