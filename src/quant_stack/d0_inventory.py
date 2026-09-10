"""Event-level Issue 009-D0 inventory built from official ledgers and provider candidates."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from datetime import date
from decimal import Decimal
from hashlib import sha256
from itertools import pairwise
from pathlib import Path

import yaml

from quant_stack.data.models import (
    CorporateActionEvent,
    CorporateActionKind,
    CorporateActionLedger,
    D0CandidateClassification,
    D0SourceRegistry,
    D0SourceSelection,
)
from quant_stack.data.sina_etf import SinaAdjustmentChange, parse_sina_adjustment_candidate
from quant_stack.data.sse_fund_inventory import load_relevant_sse_fund_announcements
from quant_stack.models import DailyBar
from quant_stack.snapshot import write_immutable

INVENTORY_VERSION = "1.0.0"


@dataclass(frozen=True)
class D0EventInventoryRow:
    """One provider or official event candidate with an evidence-bound classification."""

    candidate_id: str
    candidate_date: date
    ledger_effective_date: date | None
    event_type: str
    provider_factor_change: bool
    raw_discontinuity: bool
    official_event: bool
    classification: D0CandidateClassification
    evidence_sha256: tuple[str, ...]
    missing_evidence: tuple[str, ...]
    rationale: str


@dataclass(frozen=True)
class D0EventInventoryReport:
    """Complete event-table result for one D0 asset and its frozen inputs."""

    symbol: str
    exchange: str
    provider_candidate_sha256: str | None
    official_inventory_complete: bool
    rows: tuple[D0EventInventoryRow, ...]

    @property
    def unexplained_count(self) -> int:
        """Count rows that still lack an allowed evidence-backed classification."""
        return sum(row.classification is D0CandidateClassification.UNEXPLAINED for row in self.rows)

    @property
    def inventory_complete(self) -> bool:
        """Require both the official scan attestation and zero unexplained rows."""
        return self.official_inventory_complete and self.unexplained_count == 0


def load_d0_source_registry(path: Path, universe_path: Path) -> D0SourceRegistry:
    """Load a source registry and bind it to the exact frozen-universe bytes."""
    payload = yaml.safe_load(path.read_text(encoding="utf-8"))
    registry = D0SourceRegistry.model_validate(payload)
    actual = sha256(universe_path.read_bytes()).hexdigest()
    if registry.universe_sha256 != actual:
        raise ValueError("D0 source registry does not match the frozen universe")
    return registry


def build_event_inventory(
    selection: D0SourceSelection,
    ledger: CorporateActionLedger,
    raw_bars: list[DailyBar],
    data_root: Path,
) -> D0EventInventoryReport:
    """Reconcile provider candidates to ledger events without promoting third-party evidence."""
    if (selection.symbol, selection.exchange) != (
        ledger.instrument.symbol,
        ledger.instrument.exchange,
    ):
        raise ValueError("D0 selection and corporate-action ledger identities differ")
    changes = _load_provider_changes(selection, data_root)
    official_rows = (
        load_relevant_sse_fund_announcements(
            selection.official_inventory_sha256,
            selection.official_inventory_receipt_sha256 or "",
            selection.symbol,
            raw_bars[0].trading_date,
            raw_bars[-1].trading_date,
            data_root,
        )
        if selection.official_inventory_sha256 is not None
        else ()
    )
    directory_complete = selection.official_inventory_complete
    if selection.exchange.value == "SSE":
        directory_complete = directory_complete and _official_directory_matches_ledger(
            official_rows, ledger
        )
    research_start = raw_bars[0].trading_date
    candidates = [item for item in changes if item.candidate_date >= research_start]
    raw_dates = tuple(bar.trading_date for bar in raw_bars)
    discontinuities = _raw_discontinuities(raw_bars)
    unused = set(range(len(candidates)))
    rows: list[D0EventInventoryRow] = []
    for event in ledger.events:
        matching = [
            index
            for index in sorted(unused)
            if _candidate_matches_event(candidates[index], event, raw_dates)
        ]
        index = matching[0] if len(matching) == 1 else None
        candidate = candidates[index] if index is not None else None
        if index is not None:
            unused.remove(index)
        classification = _official_classification(event)
        missing = (
            ("contemporaneous_official_availability_evidence",)
            if classification is D0CandidateClassification.UNEXPLAINED
            else ()
        )
        candidate_date = candidate.candidate_date if candidate else event.effective_date
        rows.append(
            D0EventInventoryRow(
                candidate_id=f"{selection.symbol}:{candidate_date.isoformat()}:{event.kind.value}",
                candidate_date=candidate_date,
                ledger_effective_date=event.effective_date,
                event_type=event.kind.value,
                provider_factor_change=candidate is not None,
                raw_discontinuity=_near_discontinuity(candidate_date, discontinuities, raw_dates),
                official_event=True,
                classification=classification,
                evidence_sha256=_event_evidence_hashes(event),
                missing_evidence=missing,
                rationale=(
                    "provider candidate matched the official ledger parameter"
                    if candidate is not None
                    else "official ledger event has no matching provider candidate"
                ),
            )
        )
    for index in sorted(unused):
        candidate = candidates[index]
        event_type = "share_split" if candidate.split_ratio is not None else "cash_distribution"
        rows.append(
            D0EventInventoryRow(
                candidate_id=f"{selection.symbol}:{candidate.candidate_date.isoformat()}:{event_type}",
                candidate_date=candidate.candidate_date,
                ledger_effective_date=None,
                event_type=event_type,
                provider_factor_change=True,
                raw_discontinuity=_near_discontinuity(
                    candidate.candidate_date, discontinuities, raw_dates
                ),
                official_event=False,
                classification=D0CandidateClassification.UNEXPLAINED,
                evidence_sha256=(selection.adjustment_candidate_sha256 or "",),
                missing_evidence=("matching official corporate-action evidence",),
                rationale="provider candidate has no matching official ledger event",
            )
        )
    return D0EventInventoryReport(
        symbol=selection.symbol,
        exchange=selection.exchange.value,
        provider_candidate_sha256=selection.adjustment_candidate_sha256,
        official_inventory_complete=directory_complete,
        rows=tuple(sorted(rows, key=lambda row: (row.candidate_date, row.event_type))),
    )


def persist_event_inventory(report: D0EventInventoryReport, artifact_root: Path) -> Path:
    """Persist one deterministic, content-addressed event inventory report."""
    payload = {
        "version": INVENTORY_VERSION,
        "symbol": report.symbol,
        "exchange": report.exchange,
        "provider_candidate_sha256": report.provider_candidate_sha256,
        "official_inventory_complete": report.official_inventory_complete,
        "inventory_complete": report.inventory_complete,
        "unexplained_count": report.unexplained_count,
        "rows": [asdict(row) for row in report.rows],
    }
    content = (
        json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str).encode() + b"\n"
    )
    report_id = sha256(content).hexdigest()
    path = artifact_root / report_id / "event_inventory.json"
    write_immutable(path, content)
    return path


def _load_provider_changes(
    selection: D0SourceSelection, data_root: Path
) -> tuple[SinaAdjustmentChange, ...]:
    digest = selection.adjustment_candidate_sha256
    if digest is None:
        return ()
    path = data_root / "raw" / "sina_adjustment" / digest / "response.js"
    if not path.is_file() or sha256(path.read_bytes()).hexdigest() != digest:
        raise ValueError("D0 adjustment candidate is missing or hash-invalid")
    return parse_sina_adjustment_candidate(path.read_bytes())


def _candidate_matches_event(
    candidate: SinaAdjustmentChange,
    event: CorporateActionEvent,
    raw_dates: tuple[date, ...],
) -> bool:
    if event.kind is CorporateActionKind.CASH_DISTRIBUTION:
        value_matches = _same_reported_value(candidate.cash_per_unit, event.cash_per_unit)
    else:
        value_matches = _same_reported_value(candidate.split_ratio, event.split_ratio)
    if not value_matches:
        return False
    application = next((item for item in raw_dates if item >= event.effective_date), None)
    if application is None:
        return False
    position = raw_dates.index(application)
    allowed = {application}
    if position + 1 < len(raw_dates):
        allowed.add(raw_dates[position + 1])
    return candidate.candidate_date in allowed


def _same_reported_value(candidate: Decimal | None, official: Decimal | None) -> bool:
    """Compare a provider calculation at the decimal precision of the official parameter."""
    if candidate is None or official is None:
        return False
    exponent = official.as_tuple().exponent
    if not isinstance(exponent, int):
        return False
    quantum = Decimal(1).scaleb(exponent)
    return candidate.quantize(quantum) == official


def _official_classification(event: CorporateActionEvent) -> D0CandidateClassification:
    if event.verification_status != "official_evidence_chain_verified":
        return D0CandidateClassification.UNEXPLAINED
    if event.kind is CorporateActionKind.CASH_DISTRIBUTION:
        return D0CandidateClassification.VERIFIED_DIVIDEND
    return D0CandidateClassification.VERIFIED_SPLIT_OR_CONVERSION


def _event_evidence_hashes(event: CorporateActionEvent) -> tuple[str, ...]:
    evidence = (event.evidence, event.availability_evidence, event.value_evidence)
    return tuple(dict.fromkeys(item.sha256 for item in evidence if item is not None))


def _raw_discontinuities(raw_bars: list[DailyBar]) -> set[date]:
    result: set[date] = set()
    for previous, current in pairwise(raw_bars):
        if abs(current.close / previous.close - Decimal("1")) > Decimal("0.2"):
            result.add(current.trading_date)
    return result


def _near_discontinuity(
    candidate_date: date, discontinuities: set[date], raw_dates: tuple[date, ...]
) -> bool:
    if candidate_date in discontinuities:
        return True
    if candidate_date not in raw_dates:
        return False
    position = raw_dates.index(candidate_date)
    return position > 0 and raw_dates[position - 1] in discontinuities


def _official_directory_matches_ledger(
    announcements: tuple[object, ...], ledger: CorporateActionLedger
) -> bool:
    """Require every relevant SSE row and every ledger event to map in both directions."""
    from quant_stack.data.sse_fund_inventory import SSEFundAnnouncement

    if not announcements or any(
        not isinstance(item, SSEFundAnnouncement) for item in announcements
    ):
        return False
    typed = tuple(item for item in announcements if isinstance(item, SSEFundAnnouncement))

    def matches(announcement: SSEFundAnnouncement, event: CorporateActionEvent) -> bool:
        title_is_cash = "收益分配" in announcement.title or "分红公告" in announcement.title
        title_is_split = "份额折算" in announcement.title or "份额拆分" in announcement.title
        kind_matches = (title_is_cash and event.kind is CorporateActionKind.CASH_DISTRIBUTION) or (
            title_is_split and event.kind is CorporateActionKind.SHARE_SPLIT
        )
        return kind_matches and abs((announcement.disclosed_on - event.effective_date).days) <= 14

    return all(any(matches(row, event) for event in ledger.events) for row in typed) and all(
        any(matches(row, event) for row in typed) for event in ledger.events
    )
