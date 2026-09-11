"""Classify and compress Qlib missing member sessions using free evidence."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from datetime import date
from enum import StrEnum
from hashlib import sha256
from pathlib import Path

from quant_stack.snapshot import write_immutable
from quant_stack_v2.baostock_provider import BaoStockRow
from quant_stack_v2.qlib_qualification import QlibDailyIssue


class MissingClass(StrEnum):
    """Exhaustive classification for one missing expected member session."""

    PRE_LISTING = "PRE_LISTING"
    POST_DELISTING = "POST_DELISTING"
    MARKET_CLOSED = "MARKET_CLOSED"
    BAOSTOCK_SUSPENDED = "BAOSTOCK_SUSPENDED"
    OFFICIAL_SUSPENDED = "OFFICIAL_SUSPENDED"
    PROVIDER_CONFLICT = "PROVIDER_CONFLICT"
    UNEXPLAINED = "UNEXPLAINED"


@dataclass(frozen=True)
class SecurityLifecycle:
    """Known listing range for one security identity."""

    symbol: str
    list_date: date
    delist_date: date | None
    evidence_sha256: str


@dataclass(frozen=True)
class OfficialSuspension:
    """An exchange-confirmed suspension interval with archived evidence."""

    symbol: str
    exchange: str
    start_session: date
    end_session: date
    reason: str
    official_url: str
    artifact_sha256: str


@dataclass(frozen=True)
class ClassifiedMissing:
    """One classified Qlib missing member session."""

    symbol: str
    session: date
    classification: MissingClass
    evidence_sha256: str | None


@dataclass(frozen=True)
class SuspensionInterval:
    """Consecutive BaoStock suspension sessions compressed as one event."""

    symbol: str
    exchange: str
    start_session: date
    end_session: date
    session_count: int
    baostock_evidence_sha256: str


@dataclass(frozen=True)
class MissingCandidateInterval:
    """Consecutive missing market sessions to investigate as one evidence task."""

    symbol: str
    exchange: str
    start_session: date
    end_session: date
    session_count: int


@dataclass(frozen=True)
class FreeEvidenceAudit:
    """Complete free-evidence funnel and remaining blocking observations."""

    initial_expected_session_missing: int
    counts: dict[str, int]
    missing_sessions_count: int
    unique_suspension_intervals_count: int
    classified: tuple[ClassifiedMissing, ...]
    suspension_intervals: tuple[SuspensionInterval, ...]
    status: str

    @property
    def identity_sha256(self) -> str:
        """Return a deterministic content identity."""
        return sha256(_json(asdict(self))).hexdigest()


def classify_missing_sessions(
    *,
    issues: tuple[QlibDailyIssue, ...],
    market_sessions: tuple[date, ...],
    lifecycles: dict[str, SecurityLifecycle],
    baostock_rows: dict[tuple[str, date], tuple[BaoStockRow, str]],
    official_suspensions: tuple[OfficialSuspension, ...] = (),
) -> FreeEvidenceAudit:
    """Classify every Qlib missing date without assuming absence means suspension."""
    sessions = set(market_sessions)
    classified: list[ClassifiedMissing] = []
    for issue in issues:
        session = date.fromisoformat(issue.session)
        lifecycle = lifecycles.get(issue.symbol)
        official = next(
            (
                item
                for item in official_suspensions
                if item.symbol == issue.symbol and item.start_session <= session <= item.end_session
            ),
            None,
        )
        provider = baostock_rows.get((issue.symbol, session))
        if session not in sessions:
            result = ClassifiedMissing(issue.symbol, session, MissingClass.MARKET_CLOSED, None)
        elif lifecycle is not None and session < lifecycle.list_date:
            result = ClassifiedMissing(
                issue.symbol, session, MissingClass.PRE_LISTING, lifecycle.evidence_sha256
            )
        elif (
            lifecycle is not None
            and lifecycle.delist_date is not None
            and session > lifecycle.delist_date
        ):
            result = ClassifiedMissing(
                issue.symbol, session, MissingClass.POST_DELISTING, lifecycle.evidence_sha256
            )
        elif official is not None:
            if provider is not None and provider[0].tradestatus == 1:
                result = ClassifiedMissing(
                    issue.symbol, session, MissingClass.PROVIDER_CONFLICT, official.artifact_sha256
                )
            else:
                result = ClassifiedMissing(
                    issue.symbol, session, MissingClass.OFFICIAL_SUSPENDED, official.artifact_sha256
                )
        elif provider is not None and provider[0].tradestatus == 0:
            result = ClassifiedMissing(
                issue.symbol, session, MissingClass.BAOSTOCK_SUSPENDED, provider[1]
            )
        elif provider is not None and provider[0].tradestatus == 1:
            result = ClassifiedMissing(
                issue.symbol, session, MissingClass.PROVIDER_CONFLICT, provider[1]
            )
        else:
            result = ClassifiedMissing(issue.symbol, session, MissingClass.UNEXPLAINED, None)
        classified.append(result)
    compressed = _compress_suspensions(tuple(classified), market_sessions)
    counts = {kind.value: 0 for kind in MissingClass}
    for item in classified:
        counts[item.classification.value] += 1
    blocked = counts[MissingClass.PROVIDER_CONFLICT.value] + counts[MissingClass.UNEXPLAINED.value]
    return FreeEvidenceAudit(
        initial_expected_session_missing=len(issues),
        counts=counts,
        missing_sessions_count=len(classified),
        unique_suspension_intervals_count=len(compressed),
        classified=tuple(classified),
        suspension_intervals=compressed,
        status="QUALIFIED" if blocked == 0 else "BLOCKED_DATA",
    )


def persist_free_evidence_audit(report: FreeEvidenceAudit, artifact_root: Path) -> Path:
    """Persist the complete free-evidence funnel immutably."""
    path = artifact_root / "free_suspension_audit" / f"{report.identity_sha256}.json"
    write_immutable(path, _json(asdict(report)) + b"\n")
    return path


def compress_missing_candidates(
    issues: tuple[QlibDailyIssue, ...], market_sessions: tuple[date, ...]
) -> tuple[MissingCandidateInterval, ...]:
    """Compress consecutive Qlib missing sessions before any provider lookup."""
    positions = {session: index for index, session in enumerate(market_sessions)}
    rows = sorted(issues, key=lambda item: (item.symbol, item.session))
    result: list[MissingCandidateInterval] = []
    for issue in rows:
        session = date.fromisoformat(issue.session)
        if session not in positions:
            continue
        if (
            result
            and result[-1].symbol == issue.symbol
            and positions[session] == positions[result[-1].end_session] + 1
        ):
            prior = result[-1]
            result[-1] = MissingCandidateInterval(
                prior.symbol,
                prior.exchange,
                prior.start_session,
                session,
                prior.session_count + 1,
            )
        else:
            result.append(
                MissingCandidateInterval(
                    issue.symbol, issue.symbol[:2].upper(), session, session, 1
                )
            )
    return tuple(result)


def _compress_suspensions(
    rows: tuple[ClassifiedMissing, ...], market_sessions: tuple[date, ...]
) -> tuple[SuspensionInterval, ...]:
    session_index = {session: index for index, session in enumerate(market_sessions)}
    candidates = sorted(
        (row for row in rows if row.classification is MissingClass.BAOSTOCK_SUSPENDED),
        key=lambda row: (row.symbol, row.session),
    )
    result: list[SuspensionInterval] = []
    for row in candidates:
        if row.evidence_sha256 is None:
            raise ValueError("BaoStock suspension lacks evidence identity")
        exchange = row.symbol[:2].upper()
        if (
            result
            and result[-1].symbol == row.symbol
            and result[-1].baostock_evidence_sha256 == row.evidence_sha256
            and session_index[row.session] == session_index[result[-1].end_session] + 1
        ):
            previous = result[-1]
            result[-1] = SuspensionInterval(
                previous.symbol,
                previous.exchange,
                previous.start_session,
                row.session,
                previous.session_count + 1,
                previous.baostock_evidence_sha256,
            )
        else:
            result.append(
                SuspensionInterval(
                    row.symbol, exchange, row.session, row.session, 1, row.evidence_sha256
                )
            )
    return tuple(result)


def _json(value: object) -> bytes:
    return json.dumps(
        value, default=lambda item: item.isoformat(), sort_keys=True, separators=(",", ":")
    ).encode()
