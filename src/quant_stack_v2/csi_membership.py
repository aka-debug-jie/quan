"""Official CSI membership evidence import and point-in-time reconciliation."""

from __future__ import annotations

import json
from collections.abc import Sequence
from dataclasses import asdict, dataclass
from datetime import date
from hashlib import sha256
from pathlib import Path
from typing import Protocol

from quant_stack.snapshot import write_immutable
from quant_stack_v2.qlib_import import QlibInstrumentInterval


class MembershipInterval(Protocol):
    """Shared immutable membership fields used in daily comparison."""

    @property
    def symbol(self) -> str: ...

    @property
    def effective_from(self) -> date: ...

    @property
    def effective_to(self) -> date: ...


@dataclass(frozen=True)
class OfficialMembershipInterval:
    """One parsed CSI constituent interval tied to its original document."""

    symbol: str
    effective_from: date
    effective_to: date
    source_url: str
    published_on: date
    source_sha256: str
    locator: str
    parser_version: str


@dataclass(frozen=True)
class MembershipReconciliation:
    """Daily comparison of Qlib membership with parsed CSI official evidence."""

    universe: str
    qlib_import_sha256: str
    official_evidence_sha256: str
    research_effective_from: str
    research_effective_to: str
    sessions_checked: int
    mismatched_sessions: tuple[str, ...]
    status: str

    @property
    def identity_sha256(self) -> str:
        """Return a deterministic report identity."""
        return sha256(_canonical_json(asdict(self))).hexdigest()


def reconcile_official_membership(
    *,
    universe: str,
    qlib_import_sha256: str,
    qlib_intervals: tuple[QlibInstrumentInterval, ...],
    official_intervals: tuple[OfficialMembershipInterval, ...],
    sessions: tuple[date, ...],
    research_effective_from: date,
    research_effective_to: date,
) -> MembershipReconciliation:
    """Require identical daily membership under official CSI source documents."""
    if universe != "csi300" or not official_intervals:
        raise ValueError("official CSI300 membership evidence is required")
    _validate_official_intervals(official_intervals)
    selected = tuple(
        item for item in sessions if research_effective_from <= item <= research_effective_to
    )
    if not selected:
        raise ValueError("official membership reconciliation has no research sessions")
    official_sha = sha256(
        _canonical_json([asdict(item) for item in official_intervals])
    ).hexdigest()
    mismatch = tuple(
        item.isoformat()
        for item in selected
        if _members(qlib_intervals, item) != _members(official_intervals, item)
    )
    return MembershipReconciliation(
        universe=universe,
        qlib_import_sha256=qlib_import_sha256,
        official_evidence_sha256=official_sha,
        research_effective_from=research_effective_from.isoformat(),
        research_effective_to=research_effective_to.isoformat(),
        sessions_checked=len(selected),
        mismatched_sessions=mismatch,
        status="QUALIFIED" if not mismatch else "BLOCKED_DATA",
    )


def persist_membership_reconciliation(
    report: MembershipReconciliation, artifact_root: Path
) -> Path:
    """Persist one immutable official-membership reconciliation report."""
    path = artifact_root / "csi_membership" / f"{report.identity_sha256}.json"
    write_immutable(path, _canonical_json(asdict(report)) + b"\n")
    return path


def _validate_official_intervals(records: tuple[OfficialMembershipInterval, ...]) -> None:
    for item in records:
        if (
            item.effective_from > item.effective_to
            or not item.source_url.startswith("https://www.csindex.com.cn/")
            or len(item.source_sha256) != 64
            or not item.locator
            or not item.parser_version
        ):
            raise ValueError("official CSI interval has invalid provenance")


def _members(records: Sequence[MembershipInterval], session: date) -> tuple[str, ...]:
    return tuple(
        sorted(
            {item.symbol for item in records if item.effective_from <= session <= item.effective_to}
        )
    )


def _canonical_json(value: object) -> bytes:
    return json.dumps(
        value, default=lambda item: item.isoformat(), sort_keys=True, separators=(",", ":")
    ).encode()
