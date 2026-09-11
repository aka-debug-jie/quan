"""Evidence-bound qualification of a pinned Qlib binary tree."""

from __future__ import annotations

import json
import math
import struct
from dataclasses import asdict, dataclass
from datetime import date
from hashlib import sha256
from pathlib import Path
from typing import cast

from quant_stack.snapshot import write_immutable
from quant_stack_v2.qlib_import import QlibImportError, QlibInstrumentInterval

REQUIRED_FIELDS = ("open", "high", "low", "close", "volume", "factor")
ISSUE_KINDS = frozenset(
    {
        "MISSING_FEATURE_DIRECTORY",
        "MISSING_FEATURE_FILE",
        "INVALID_BINARY_INDEX",
        "MISSING_OR_SUSPENDED_UNVERIFIED",
        "ILLEGAL_ADJUSTED_OHLC",
        "ILLEGAL_FACTOR",
        "UNRECONSTRUCTABLE_RAW_OHLC",
        "ZERO_MEMBER_SESSIONS",
    }
)


@dataclass(frozen=True)
class QlibDailyIssue:
    """One auditable problem for a symbol that was a PIT member on a session."""

    symbol: str
    session: str
    kind: str
    detail: str


@dataclass(frozen=True)
class QlibDailyAudit:
    """Deterministic full-range audit with every failing member/session retained."""

    schema_version: int
    universe: str
    import_report_sha256: str
    research_effective_from: str
    research_effective_to: str
    member_sessions_checked: int
    valid_member_sessions: int
    issues: tuple[QlibDailyIssue, ...]

    @property
    def identity_sha256(self) -> str:
        """Return a content identity independent of execution time."""
        return sha256(_canonical_json(asdict(self))).hexdigest()

    @property
    def status(self) -> str:
        """Return the fail-closed data status for this complete audit."""
        return "QUALIFIED" if not self.issues else "BLOCKED_DATA"


def audit_qlib_member_sessions(
    root: Path,
    *,
    universe: str,
    intervals: tuple[QlibInstrumentInterval, ...],
    sessions: tuple[date, ...],
    import_report_sha256: str,
    research_effective_from: date,
    research_effective_to: date,
) -> QlibDailyAudit:
    """Audit every active member/session without treating a missing bar as a halt.

    Qlib feature files store a float32 calendar start index followed by values.
    Values that are absent, invalid, or impossible to invert through ``factor``
    are retained as explicit failures; only an independent official trading-state
    report may later classify one as a suspension.
    """
    if universe not in {"csi300", "csi500"}:
        raise QlibImportError("daily audit universe must be csi300 or csi500")
    if not import_report_sha256 or len(import_report_sha256) != 64:
        raise QlibImportError("daily audit requires an import report SHA-256")
    selected = tuple(
        session
        for session in sessions
        if research_effective_from <= session <= research_effective_to
    )
    if not selected:
        raise QlibImportError("daily audit range has no Qlib calendar sessions")
    members = {
        session: tuple(
            sorted(
                item.symbol
                for item in intervals
                if item.effective_from <= session <= item.effective_to
            )
        )
        for session in selected
    }
    issue_rows: list[QlibDailyIssue] = []
    valid = 0
    checked = 0
    cache: dict[str, dict[str, dict[date, float]] | QlibDailyIssue] = {}
    for session in selected:
        for symbol in members[session]:
            checked += 1
            loaded = cache.get(symbol)
            if loaded is None:
                loaded = _load_symbol(root, symbol, sessions)
                cache[symbol] = loaded
            if isinstance(loaded, QlibDailyIssue):
                issue_rows.append(_at_session(loaded, session))
                continue
            issue = _validate_bar(symbol, session, loaded)
            if issue is None:
                valid += 1
            else:
                issue_rows.append(issue)
    if checked == 0:
        issue_rows.append(QlibDailyIssue("", "", "ZERO_MEMBER_SESSIONS", "no active PIT members"))
    return QlibDailyAudit(
        schema_version=1,
        universe=universe,
        import_report_sha256=import_report_sha256,
        research_effective_from=research_effective_from.isoformat(),
        research_effective_to=research_effective_to.isoformat(),
        member_sessions_checked=checked,
        valid_member_sessions=valid,
        issues=tuple(issue_rows),
    )


def persist_daily_audit(audit: QlibDailyAudit, artifact_root: Path) -> Path:
    """Write the complete content-addressed audit, including all issue rows."""
    content = _canonical_json(asdict(audit)) + b"\n"
    path = artifact_root / audit.universe / f"{audit.identity_sha256}.json"
    write_immutable(path, content)
    return path


def _load_symbol(
    root: Path, symbol: str, sessions: tuple[date, ...]
) -> dict[str, dict[date, float]] | QlibDailyIssue:
    directory = root / "features" / symbol
    if not directory.is_dir():
        return QlibDailyIssue(symbol, "", "MISSING_FEATURE_DIRECTORY", "feature directory absent")
    values: dict[str, dict[date, float]] = {}
    for field in REQUIRED_FIELDS:
        path = directory / f"{field}.day.bin"
        if not path.is_file():
            return QlibDailyIssue(symbol, "", "MISSING_FEATURE_FILE", field)
        try:
            values[field] = _read_series(path, sessions)
        except ValueError as error:
            return QlibDailyIssue(symbol, "", "INVALID_BINARY_INDEX", str(error))
    return values


def _read_series(path: Path, sessions: tuple[date, ...]) -> dict[date, float]:
    raw = path.read_bytes()
    if len(raw) < 8 or len(raw) % 4:
        raise ValueError(f"{path.name}: invalid float32 payload")
    decoded = struct.unpack(f"<{len(raw) // 4}f", raw)
    start = decoded[0]
    if not math.isfinite(start) or start < 0 or not start.is_integer():
        raise ValueError(f"{path.name}: invalid calendar start index")
    start_index = int(start)
    values = decoded[1:]
    if start_index + len(values) > len(sessions):
        raise ValueError(f"{path.name}: values exceed calendar")
    return {sessions[start_index + index]: value for index, value in enumerate(values)}


def _validate_bar(
    symbol: str, session: date, fields: dict[str, dict[date, float]]
) -> QlibDailyIssue | None:
    values = {field: fields[field].get(session) for field in REQUIRED_FIELDS}
    missing_fields = tuple(
        field for field, value in values.items() if value is None or not math.isfinite(value)
    )
    if missing_fields:
        return QlibDailyIssue(
            symbol,
            session.isoformat(),
            "MISSING_OR_SUSPENDED_UNVERIFIED",
            f"non-finite or absent fields: {','.join(missing_fields)}",
        )
    factor = values["factor"]
    assert factor is not None
    if factor <= 0:
        return QlibDailyIssue(
            symbol, session.isoformat(), "ILLEGAL_FACTOR", "factor must be positive"
        )
    open_, high, low, close, volume = tuple(
        cast(float, values[item]) for item in ("open", "high", "low", "close", "volume")
    )
    if (
        min(open_, high, low, close) <= 0
        or volume < 0
        or low > min(open_, close)
        or high < max(open_, close)
    ):
        return QlibDailyIssue(
            symbol, session.isoformat(), "ILLEGAL_ADJUSTED_OHLC", "OHLCV invariant failed"
        )
    reconstructed = (open_ / factor, high / factor, low / factor, close / factor)
    if not all(math.isfinite(value) and value > 0 for value in reconstructed):
        return QlibDailyIssue(
            symbol,
            session.isoformat(),
            "UNRECONSTRUCTABLE_RAW_OHLC",
            "inverse factor failed",
        )
    return None


def _at_session(issue: QlibDailyIssue, session: date) -> QlibDailyIssue:
    return QlibDailyIssue(issue.symbol, session.isoformat(), issue.kind, issue.detail)


def _canonical_json(value: object) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
