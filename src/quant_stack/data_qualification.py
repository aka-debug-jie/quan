"""Frozen-universe data qualification before any locked research evaluation."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from datetime import date
from hashlib import sha256
from pathlib import Path

import pyarrow.parquet as pq  # type: ignore[import-untyped]

from quant_stack.data.calendar import CalendarSourceError, ExchangeCalendarStore
from quant_stack.data.corporate_actions import load_corporate_action_ledger
from quant_stack.data.evidence import EvidenceArchiveError, require_corporate_action_evidence
from quant_stack.data.ingest import load_etf_universe
from quant_stack.data.models import ETFUniverseInstrument
from quant_stack.models import PriceBasis
from quant_stack.research_inputs import preflight_causal_universe
from quant_stack.snapshot import write_immutable


@dataclass(frozen=True)
class CandidateInventory:
    """Provider and raw-price diagnostics; neither is official corporate-action evidence."""

    provider_factor_change_points: int
    raw_discontinuity_dates: tuple[str, ...]
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
    ledger_evidence_archived: bool
    pit_causal_safe: bool
    causal_adjusted_available: bool
    causal_manifest_id: str | None
    execution_raw_available: bool
    cross_provider_reconciliation: bool
    deterministic_reproduction: bool
    candidate_inventory: CandidateInventory
    result: str
    reasons: tuple[str, ...]


@dataclass(frozen=True)
class UniverseDataQualificationReport:
    """A complete scan of the frozen universe, not a partial remediation result."""

    universe_sha256: str
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
) -> UniverseDataQualificationReport:
    """Audit every frozen ETF asset without using provider qfq as canonical adjusted data."""
    universe = load_etf_universe(universe_path)
    if not universe.instruments:
        raise ValueError("frozen universe must contain instruments")
    causal_preflight = preflight_causal_universe(
        universe_path, data_root / "canonical" / "manifests", data_root
    )
    causal_by_identity = {(item.symbol, item.exchange): item for item in causal_preflight.inputs}
    assets: list[AssetQualification] = []
    calendar = ExchangeCalendarStore(calendar_root)
    for instrument in universe.instruments:
        symbol = instrument.symbol
        exchange = instrument.exchange.value
        raw_manifest = _selected_raw_manifest(data_root / "manifests", symbol, exchange)
        ledger_path = ledger_root / f"{symbol}_v1.yaml"
        ledger_status, evidence_archived = _ledger_status(ledger_path, data_root)
        causal_input = causal_by_identity.get((symbol, exchange))
        inventory = _candidate_inventory(raw_manifest, data_root)
        expected_session_coverage = _expected_session_coverage(
            raw_manifest, instrument, data_root, calendar
        )
        raw_coverage = raw_manifest is not None and expected_session_coverage
        raw_valid = _manifest_files_match(raw_manifest, data_root)
        causal_available = causal_input is not None
        pit_safe = ledger_status == "complete" and evidence_archived and causal_available
        reasons = _qualification_reasons(
            raw_coverage,
            expected_session_coverage,
            raw_valid,
            ledger_status,
            evidence_archived,
            causal_available,
            inventory,
            False,
            False,
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
                ledger_evidence_archived=evidence_archived,
                pit_causal_safe=pit_safe,
                causal_adjusted_available=causal_available,
                causal_manifest_id=causal_input.manifest_id if causal_input else None,
                execution_raw_available=raw_coverage and raw_valid,
                cross_provider_reconciliation=False,
                deterministic_reproduction=False,
                candidate_inventory=inventory,
                result="QUALIFIED" if not reasons else "NOT_QUALIFIED",
                reasons=tuple(reasons),
            )
        )
    return UniverseDataQualificationReport(
        universe_sha256=sha256(universe_path.read_bytes()).hexdigest(), assets=tuple(assets)
    )


def persist_qualification_report(
    report: UniverseDataQualificationReport, artifact_root: Path
) -> Path:
    """Write a deterministic qualification artifact that cannot overwrite a different report."""
    payload = {
        "universe_sha256": report.universe_sha256,
        "all_qualified": report.all_qualified,
        "assets": [asdict(asset) for asset in report.assets],
    }
    content = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode() + b"\n"
    report_id = sha256(content).hexdigest()
    destination = artifact_root / report_id / "qualification.json"
    write_immutable(destination, content)
    return destination


def _selected_raw_manifest(
    manifest_root: Path, symbol: str, exchange: str
) -> dict[str, object] | None:
    """Select the latest complete raw manifest for one frozen instrument, if it exists."""
    candidates: list[dict[str, object]] = []
    paths = (*manifest_root.glob("*.json"), *(manifest_root / "providers").glob("*.json"))
    for path in sorted(paths):
        payload = json.loads(path.read_text(encoding="utf-8"))
        request = payload.get("request")
        price_basis = (
            request.get("price_basis") if isinstance(request, dict) else payload.get("price_basis")
        )
        if price_basis != PriceBasis.RAW.value:
            continue
        instrument = (
            request.get("instrument") if isinstance(request, dict) else payload.get("instrument")
        )
        if not isinstance(instrument, dict):
            continue
        if instrument.get("symbol") == symbol and instrument.get("exchange") == exchange:
            candidates.append(payload)
    complete = [item for item in candidates if item.get("coverage_complete") is True]
    if complete:
        return sorted(complete, key=lambda item: str(item.get("first_captured_at", "")))[-1]
    if not candidates:
        return None
    return sorted(candidates, key=lambda item: str(item.get("retrieved_at", "")))[-1]


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


def _candidate_inventory(
    raw_manifest: dict[str, object] | None, data_root: Path
) -> CandidateInventory:
    """Inventory every provider factor change and raw one-session discontinuity diagnostic."""
    if raw_manifest is None:
        return CandidateInventory(0, (), 0)
    symbol = _request_identity(raw_manifest, "symbol")
    exchange = _request_identity(raw_manifest, "exchange")
    if symbol is None or exchange is None:
        return CandidateInventory(0, (), 0)
    qfq_manifest = _matching_qfq_manifest(data_root / "manifests", symbol, exchange)
    if qfq_manifest is None:
        return CandidateInventory(0, (), 0)
    raw_path = _normalized_path(raw_manifest, data_root)
    qfq_path = _normalized_path(qfq_manifest, data_root)
    if raw_path is None or qfq_path is None:
        return CandidateInventory(0, (), 0)
    raw = pq.read_table(raw_path).to_pandas().sort_values("trading_date")
    qfq = pq.read_table(qfq_path).to_pandas().sort_values("trading_date")
    if len(raw) != len(qfq) or not raw.trading_date.equals(qfq.trading_date):
        return CandidateInventory(0, (), 0)
    factor = qfq.close.astype(float) / raw.close.astype(float)
    factor_changes = int(factor.ne(factor.shift()).sum())
    raw_return = raw.close.astype(float).pct_change().abs()
    discontinuities = tuple(raw.loc[raw_return > 0.2, "trading_date"].astype(str))
    return CandidateInventory(factor_changes, discontinuities, factor_changes)


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
    if not causal_available:
        reasons.append("canonical_causal_adjusted_missing")
    if inventory.unresolved_factor_change_points:
        reasons.append("unresolved_provider_factor_change_points")
    if not cross_provider_reconciliation:
        reasons.append("cross_provider_reconciliation_unverified")
    if not deterministic_reproduction:
        reasons.append("deterministic_reproduction_unverified")
    return reasons
