"""Offline, content-addressed inspection of a captured Qlib binary archive."""

from __future__ import annotations

import json
import shutil
import tarfile
import tempfile
from dataclasses import asdict, dataclass
from datetime import date
from hashlib import sha256
from pathlib import Path

from quant_stack.snapshot import write_immutable


class QlibImportError(ValueError):
    """Raised when a Qlib archive cannot meet the V2 import contract."""


@dataclass(frozen=True)
class QlibInstrumentInterval:
    """One source-declared, point-in-time universe membership interval."""

    symbol: str
    effective_from: date
    effective_to: date


@dataclass(frozen=True)
class QlibImportReport:
    """Immutable report produced only from a verified local Qlib archive."""

    schema_version: int
    archive_sha256: str
    manifest_sha256: str
    extracted_tree_sha256: str
    imported_at_utc: None
    calendar_sessions: int
    sessions: tuple[str, ...]
    first_session: str | None
    last_session: str | None
    feature_symbols: int
    missing_price_or_factor_symbols: tuple[str, ...]
    csi300_intervals: tuple[QlibInstrumentInterval, ...]
    csi500_intervals: tuple[QlibInstrumentInterval, ...]
    factor_reconstruction_status: str
    status: str

    @property
    def identity_sha256(self) -> str:
        """Return a stable identity for the complete import evidence."""
        payload = _report_json(self)
        return sha256(payload).hexdigest()


def import_qlib_archive(
    archive_path: Path,
    manifest_path: Path,
    output_root: Path,
    *,
    expected_archive_sha256: str,
    expected_manifest_sha256: str,
) -> tuple[Path, QlibImportReport]:
    """Safely extract a verified archive and publish its deterministic import report."""
    _require_hash(archive_path, expected_archive_sha256, "archive")
    _require_hash(manifest_path, expected_manifest_sha256, "manifest")
    _require_manifest_json(manifest_path)
    extracted = _safe_extract(archive_path, output_root / expected_archive_sha256)
    tree_hash = tree_sha256(extracted)
    report = _inspect_tree(
        extracted,
        archive_sha256=expected_archive_sha256,
        manifest_sha256=expected_manifest_sha256,
        tree_sha256=tree_hash,
    )
    encoded = _report_json(report) + b"\n"
    report_path = (
        output_root / expected_archive_sha256 / "reports" / f"{report.identity_sha256}.json"
    )
    write_immutable(report_path, encoded)
    return report_path, report


def load_qlib_import_report(path: Path) -> QlibImportReport:
    """Load one machine-readable Qlib import report without touching the network."""
    payload = json.loads(path.read_text(encoding="utf-8"))
    for universe in ("csi300_intervals", "csi500_intervals"):
        payload[universe] = tuple(
            QlibInstrumentInterval(
                symbol=item["symbol"],
                effective_from=date.fromisoformat(item["effective_from"]),
                effective_to=date.fromisoformat(item["effective_to"]),
            )
            for item in payload[universe]
        )
    payload["missing_price_or_factor_symbols"] = tuple(payload["missing_price_or_factor_symbols"])
    return QlibImportReport(**payload)


def _require_hash(path: Path, expected: str, label: str) -> None:
    if not path.is_file() or _file_sha256(path) != expected:
        raise QlibImportError(f"Qlib {label} does not match its pinned SHA-256")


def _require_manifest_json(path: Path) -> None:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise QlibImportError("Qlib manifest is not valid JSON") from error
    if not isinstance(payload, dict):
        raise QlibImportError("Qlib manifest must be a JSON object")


def _safe_extract(archive_path: Path, archive_root: Path) -> Path:
    archive_root.mkdir(parents=True, exist_ok=True)
    temporary = Path(tempfile.mkdtemp(prefix=".extract-", dir=archive_root))
    with tarfile.open(archive_path, "r:gz") as archive:
        members = archive.getmembers()
        if not members:
            raise QlibImportError("Qlib archive is empty")
        try:
            for member in members:
                target = (temporary / member.name).resolve()
                if (
                    not target.is_relative_to(temporary.resolve())
                    or member.issym()
                    or member.islnk()
                ):
                    raise QlibImportError("Qlib archive contains an unsafe member")
            archive.extractall(temporary, members, filter="data")
            tree_hash = tree_sha256(temporary)
            destination = archive_root / "trees" / tree_hash
            destination.parent.mkdir(parents=True, exist_ok=True)
            if destination.exists():
                if tree_sha256(destination) != tree_hash:
                    raise QlibImportError("existing Qlib extraction tree differs from its identity")
                shutil.rmtree(temporary)
            else:
                try:
                    temporary.rename(destination)
                except OSError:
                    if not destination.exists():
                        raise
                    shutil.rmtree(temporary)
            return destination
        except BaseException:
            shutil.rmtree(temporary, ignore_errors=True)
            raise


def _inspect_tree(
    root: Path, *, archive_sha256: str, manifest_sha256: str, tree_sha256: str
) -> QlibImportReport:
    calendar = _single_path(root, "calendars/day.txt")
    csi300 = _single_path(root, "instruments/csi300.txt")
    csi500 = _single_path(root, "instruments/csi500.txt")
    sessions = _load_sessions(calendar)
    csi300_intervals = _load_intervals(csi300)
    csi500_intervals = _load_intervals(csi500)
    symbols = {item.symbol for item in csi300_intervals + csi500_intervals}
    missing = tuple(sorted(symbol for symbol in symbols if not _has_price_factor(root, symbol)))
    # A Qlib factor file is not evidence of its economic reconstruction semantics.
    # Qualification must remain blocked until separately archived source evidence is added.
    status = "BLOCKED_DATA"
    return QlibImportReport(
        schema_version=1,
        archive_sha256=archive_sha256,
        manifest_sha256=manifest_sha256,
        extracted_tree_sha256=tree_sha256,
        imported_at_utc=None,
        calendar_sessions=len(sessions),
        sessions=tuple(item.isoformat() for item in sessions),
        first_session=sessions[0].isoformat() if sessions else None,
        last_session=sessions[-1].isoformat() if sessions else None,
        feature_symbols=len(symbols),
        missing_price_or_factor_symbols=missing,
        csi300_intervals=csi300_intervals,
        csi500_intervals=csi500_intervals,
        factor_reconstruction_status="UNVERIFIED_FACTOR_SEMANTICS",
        status=status,
    )


def _single_path(root: Path, suffix: str) -> Path:
    matches = tuple(root.rglob(suffix))
    if len(matches) != 1:
        raise QlibImportError(f"Qlib archive must contain exactly one {suffix}")
    return matches[0]


def _load_sessions(path: Path) -> tuple[date, ...]:
    sessions = tuple(
        date.fromisoformat(line.strip()) for line in path.read_text().splitlines() if line.strip()
    )
    if not sessions or sessions != tuple(sorted(set(sessions))):
        raise QlibImportError("Qlib calendar must contain unique ascending sessions")
    return sessions


def _load_intervals(path: Path) -> tuple[QlibInstrumentInterval, ...]:
    entries: list[QlibInstrumentInterval] = []
    for raw in path.read_text(encoding="utf-8").splitlines():
        fields = raw.split("\t")
        if len(fields) != 3 or not all(fields):
            raise QlibImportError("Qlib instrument records require symbol and two dates")
        start, end = date.fromisoformat(fields[1]), date.fromisoformat(fields[2])
        if start > end:
            raise QlibImportError("Qlib instrument interval is reversed")
        entries.append(QlibInstrumentInterval(fields[0].lower(), start, end))
    if not entries:
        raise QlibImportError("Qlib index universe is empty")
    return tuple(
        sorted(entries, key=lambda item: (item.symbol, item.effective_from, item.effective_to))
    )


def _has_price_factor(root: Path, symbol: str) -> bool:
    matches = tuple(root.rglob(f"features/{symbol}"))
    if len(matches) != 1:
        return False
    feature_directory = matches[0]
    return all(
        (feature_directory / f"{field}.day.bin").is_file() for field in ("open", "close", "factor")
    )


def tree_sha256(root: Path) -> str:
    digest = sha256()
    for path in sorted(item for item in root.rglob("*") if item.is_file()):
        relative = path.relative_to(root).as_posix().encode()
        digest.update(relative + b"\0" + _file_sha256(path).encode() + b"\n")
    return digest.hexdigest()


def _file_sha256(path: Path) -> str:
    digest = sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def _report_json(report: QlibImportReport) -> bytes:
    """Serialize date-bearing import evidence canonically for immutable storage."""
    return json.dumps(
        asdict(report),
        default=_json_default,
        sort_keys=True,
        separators=(",", ":"),
    ).encode()


def _json_default(value: object) -> str:
    """Encode only ISO calendar dates; reject every other unexpected object."""
    if isinstance(value, date):
        return value.isoformat()
    raise TypeError(f"unsupported report value: {type(value).__name__}")
