"""Content-addressed capture and verification for asset-level non-trading evidence."""

from __future__ import annotations

from collections.abc import Callable, Iterable
from hashlib import sha256
from pathlib import Path
from urllib.request import Request, urlopen

from quant_stack.data.models import DocumentedNonTradingEvent, OfficialEvidence
from quant_stack.snapshot import write_immutable

EvidenceFetcher = Callable[[str], bytes]


class EvidenceArchiveError(ValueError):
    """Raised when a documented non-trading event lacks a valid local evidence body."""


def non_trading_evidence_archive_path(data_root: Path, evidence: OfficialEvidence) -> Path:
    """Return the immutable local location of one official non-trading evidence document."""
    return data_root / "raw" / "non_trading_evidence" / evidence.sha256 / "evidence.pdf"


def require_non_trading_evidence(
    events: Iterable[DocumentedNonTradingEvent],
    data_root: Path,
) -> None:
    """Reject an exception unless its evidence body is locally present and hash-verified."""
    for evidence in _unique_evidence(events):
        archive_path = non_trading_evidence_archive_path(data_root, evidence)
        if not archive_path.is_file():
            raise EvidenceArchiveError(
                f"missing local non-trading evidence archive: {archive_path}"
            )
        if _sha256(archive_path.read_bytes()) != evidence.sha256:
            raise EvidenceArchiveError(f"non-trading evidence hash mismatch: {archive_path}")


def capture_non_trading_evidence(
    events: Iterable[DocumentedNonTradingEvent],
    data_root: Path,
    fetcher: EvidenceFetcher | None = None,
) -> tuple[Path, ...]:
    """Fetch, validate, and immutably archive each unique official evidence document."""
    fetch = fetcher or _fetch_evidence_bytes
    archive_paths: list[Path] = []
    for evidence in _unique_evidence(events):
        archive_path = non_trading_evidence_archive_path(data_root, evidence)
        if archive_path.is_file():
            if _sha256(archive_path.read_bytes()) != evidence.sha256:
                raise EvidenceArchiveError(f"non-trading evidence hash mismatch: {archive_path}")
        else:
            content = fetch(evidence.url)
            if _sha256(content) != evidence.sha256:
                raise EvidenceArchiveError(
                    f"non-trading evidence content does not match configured hash: {evidence.url}"
                )
            write_immutable(archive_path, content)
        archive_paths.append(archive_path)
    return tuple(archive_paths)


def _unique_evidence(events: Iterable[DocumentedNonTradingEvent]) -> tuple[OfficialEvidence, ...]:
    """Return evidence once per content hash while preserving configuration order."""
    unique: dict[str, OfficialEvidence] = {}
    for event in events:
        unique.setdefault(event.evidence.sha256, event.evidence)
    return tuple(unique.values())


def _fetch_evidence_bytes(url: str) -> bytes:
    """Download one official evidence document with a bounded timeout."""
    request = Request(url, headers={"User-Agent": "quant-stack-evidence/1.0"})
    try:
        with urlopen(request, timeout=30) as response:
            return bytes(response.read())
    except OSError as error:
        raise EvidenceArchiveError(f"unable to fetch non-trading evidence: {url}") from error


def _sha256(content: bytes) -> str:
    """Return the lowercase SHA-256 digest of immutable evidence content."""
    return sha256(content).hexdigest()
