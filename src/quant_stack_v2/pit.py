"""Point-in-time index membership and conservative qualification checks for V2."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from datetime import date
from hashlib import sha256
from itertools import pairwise
from pathlib import Path

from quant_stack.snapshot import write_immutable
from quant_stack_v2.qlib_import import QlibImportError, QlibInstrumentInterval


@dataclass(frozen=True)
class PITUniverse:
    """An immutable index universe whose membership is resolved only as of a session."""

    name: str
    intervals: tuple[QlibInstrumentInterval, ...]

    def members_on(self, session: date) -> tuple[str, ...]:
        """Return only symbols whose source interval includes the requested session."""
        return tuple(
            sorted(
                {
                    item.symbol
                    for item in self.intervals
                    if item.effective_from <= session <= item.effective_to
                }
            )
        )


@dataclass(frozen=True)
class PITQualificationReport:
    """Forward and reverse membership checks for one point-in-time universe."""

    universe: str
    source_import_report_sha256: str
    research_effective_from: str
    research_effective_to: str
    sessions_checked: int
    pre_research_unavailable_members: tuple[str, ...]
    empty_membership_sessions: tuple[str, ...]
    unavailable_members: tuple[str, ...]
    unexplained_sessions: tuple[str, ...]
    status: str

    @property
    def identity_sha256(self) -> str:
        """Return the deterministic identity of this qualification evidence."""
        payload = json.dumps(asdict(self), sort_keys=True, separators=(",", ":")).encode()
        return sha256(payload).hexdigest()


def build_pit_universe(name: str, intervals: tuple[QlibInstrumentInterval, ...]) -> PITUniverse:
    """Validate interval identities and return a point-in-time membership resolver."""
    if not intervals:
        raise QlibImportError("PIT universe requires source membership intervals")
    by_symbol: dict[str, list[QlibInstrumentInterval]] = {}
    for item in intervals:
        by_symbol.setdefault(item.symbol, []).append(item)
    for records in by_symbol.values():
        records.sort(key=lambda item: item.effective_from)
        for previous, current in pairwise(records):
            if current.effective_from <= previous.effective_to:
                raise QlibImportError("PIT membership intervals overlap")
    return PITUniverse(name=name, intervals=intervals)


def qualify_pit_universe(
    universe: PITUniverse,
    sessions: tuple[date, ...],
    available_symbols: set[str],
    source_import_report_sha256: str,
    research_effective_from: date | None = None,
    research_effective_to: date | None = None,
) -> PITQualificationReport:
    """Reject missing source membership or non-tradable members without synthesizing bars."""
    if not source_import_report_sha256 or len(source_import_report_sha256) != 64:
        raise QlibImportError("qualification requires its source import report identity")
    if not sessions or sessions != tuple(sorted(set(sessions))):
        raise QlibImportError("qualification requires unique ascending trading sessions")
    effective_from = research_effective_from or sessions[0]
    effective_to = research_effective_to or sessions[-1]
    if effective_from > effective_to:
        raise QlibImportError("qualification research range is reversed")
    research_sessions = tuple(
        session for session in sessions if effective_from <= session <= effective_to
    )
    if not research_sessions:
        raise QlibImportError("qualification research range has no source sessions")
    empty = tuple(
        session.isoformat() for session in research_sessions if not universe.members_on(session)
    )
    relevant = {
        item.symbol
        for item in universe.intervals
        if item.effective_from <= effective_to and item.effective_to >= effective_from
    }
    declared = {item.symbol for item in universe.intervals}
    unavailable = tuple(sorted(relevant - available_symbols))
    pre_research_unavailable = tuple(sorted((declared - relevant) - available_symbols))
    unexplained = (*empty, *(f"missing_symbol:{symbol}" for symbol in unavailable))
    return PITQualificationReport(
        universe=universe.name,
        source_import_report_sha256=source_import_report_sha256,
        research_effective_from=effective_from.isoformat(),
        research_effective_to=effective_to.isoformat(),
        sessions_checked=len(research_sessions),
        pre_research_unavailable_members=pre_research_unavailable,
        empty_membership_sessions=empty,
        unavailable_members=unavailable,
        unexplained_sessions=unexplained,
        status="QUALIFIED" if not unexplained else "BLOCKED_DATA",
    )


def persist_pit_qualification(report: PITQualificationReport, artifact_root: Path) -> Path:
    """Publish a content-addressed qualification report without mutable status files."""
    content = json.dumps(asdict(report), sort_keys=True, separators=(",", ":")).encode() + b"\n"
    path = artifact_root / report.universe / f"{report.identity_sha256}.json"
    write_immutable(path, content)
    return path


def load_pit_qualification(path: Path) -> PITQualificationReport:
    """Load one immutable PIT report and reject a mismatched content-addressed filename."""
    payload = json.loads(path.read_text(encoding="utf-8"))
    report = PITQualificationReport(
        universe=str(payload["universe"]),
        source_import_report_sha256=str(payload["source_import_report_sha256"]),
        research_effective_from=str(payload["research_effective_from"]),
        research_effective_to=str(payload["research_effective_to"]),
        sessions_checked=int(payload["sessions_checked"]),
        pre_research_unavailable_members=tuple(payload["pre_research_unavailable_members"]),
        empty_membership_sessions=tuple(payload["empty_membership_sessions"]),
        unavailable_members=tuple(payload["unavailable_members"]),
        unexplained_sessions=tuple(payload["unexplained_sessions"]),
        status=str(payload["status"]),
    )
    if path.stem != report.identity_sha256:
        raise QlibImportError("PIT qualification filename does not match its content identity")
    return report
