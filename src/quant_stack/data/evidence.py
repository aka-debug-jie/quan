"""Content-addressed capture and verification for asset-level non-trading evidence."""

from __future__ import annotations

import json
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from datetime import UTC, datetime
from hashlib import sha256
from pathlib import Path
from urllib.request import Request, urlopen

from quant_stack.data.models import (
    CorporateActionEvent,
    DocumentedNonTradingEvent,
    OfficialEvidence,
)
from quant_stack.snapshot import write_immutable

EvidenceFetcher = Callable[[str], bytes]


@dataclass(frozen=True)
class CapturedEvidence:
    """A first-party evidence body together with the HTTP receipt captured at retrieval."""

    content: bytes
    http_metadata: dict[str, str]
    retrieved_at: datetime


class EvidenceArchiveError(ValueError):
    """Raised when a documented non-trading event lacks a valid local evidence body."""


def non_trading_evidence_archive_path(data_root: Path, evidence: OfficialEvidence) -> Path:
    """Return the immutable local location of one official non-trading evidence document."""
    return data_root / "raw" / "non_trading_evidence" / evidence.sha256 / "evidence.pdf"


def corporate_action_evidence_archive_path(data_root: Path, evidence: OfficialEvidence) -> Path:
    """Return the immutable local location of one corporate-action source body."""
    return data_root / "raw" / "corporate_action_evidence" / evidence.sha256 / "evidence.bin"


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


def require_corporate_action_evidence(
    events: Iterable[CorporateActionEvent],
    data_root: Path,
) -> None:
    """Reject a corporate-action ledger whose evidence is absent or altered locally."""
    _require_evidence(
        _unique_corporate_action_evidence(events),
        data_root,
        "corporate_action_evidence",
        "evidence.bin",
    )


def capture_corporate_action_evidence(
    events: Iterable[CorporateActionEvent],
    data_root: Path,
    fetcher: EvidenceFetcher | None = None,
) -> tuple[Path, ...]:
    """Fetch, validate, and immutably archive official corporate-action evidence."""
    return _capture_evidence(
        _unique_corporate_action_evidence(events),
        data_root,
        "corporate_action_evidence",
        fetcher,
        "evidence.bin",
    )


def archive_corporate_action_source(
    url: str,
    data_root: Path,
    fetcher: Callable[[str], CapturedEvidence] | None = None,
) -> OfficialEvidence:
    """Archive a first-party corporate-action source before its SHA is added to a ledger."""
    captured = (fetcher or _fetch_evidence_with_receipt)(url)
    digest = _sha256(captured.content)
    evidence = OfficialEvidence(url=url, sha256=digest, published_on=captured.retrieved_at.date())
    evidence_path = corporate_action_evidence_archive_path(data_root, evidence)
    write_immutable(evidence_path, captured.content)
    receipt_path = evidence_path.with_name("receipt.json")
    if not receipt_path.exists():
        receipt = {
            "source_url": url,
            "retrieved_at": captured.retrieved_at.astimezone(UTC).isoformat(),
            "http_metadata": captured.http_metadata,
            "sha256": digest,
        }
        write_immutable(
            receipt_path,
            json.dumps(receipt, ensure_ascii=False, sort_keys=True, indent=2).encode("utf-8")
            + b"\n",
        )
    return evidence


def _unique_evidence(events: Iterable[DocumentedNonTradingEvent]) -> tuple[OfficialEvidence, ...]:
    """Return evidence once per content hash while preserving configuration order."""
    unique: dict[str, OfficialEvidence] = {}
    for event in events:
        unique.setdefault(event.evidence.sha256, event.evidence)
    return tuple(unique.values())


def _unique_corporate_action_evidence(
    events: Iterable[CorporateActionEvent],
) -> tuple[OfficialEvidence, ...]:
    """Return corporate-action evidence once per content hash in ledger order."""
    unique: dict[str, OfficialEvidence] = {}
    for event in events:
        unique.setdefault(event.evidence.sha256, event.evidence)
    return tuple(unique.values())


def _require_evidence(
    evidence_items: Iterable[OfficialEvidence],
    data_root: Path,
    category: str,
    filename: str = "evidence.pdf",
) -> None:
    """Verify local evidence bodies for one evidence category."""
    for evidence in evidence_items:
        archive_path = data_root / "raw" / category / evidence.sha256 / filename
        if not archive_path.is_file():
            raise EvidenceArchiveError(f"missing local evidence archive: {archive_path}")
        if _sha256(archive_path.read_bytes()) != evidence.sha256:
            raise EvidenceArchiveError(f"evidence hash mismatch: {archive_path}")


def _capture_evidence(
    evidence_items: Iterable[OfficialEvidence],
    data_root: Path,
    category: str,
    fetcher: EvidenceFetcher | None,
    filename: str = "evidence.pdf",
) -> tuple[Path, ...]:
    """Capture one evidence category under its content-addressed raw root."""
    fetch = fetcher or _fetch_evidence_bytes
    archive_paths: list[Path] = []
    for evidence in evidence_items:
        archive_path = data_root / "raw" / category / evidence.sha256 / filename
        if archive_path.is_file():
            if _sha256(archive_path.read_bytes()) != evidence.sha256:
                raise EvidenceArchiveError(f"evidence hash mismatch: {archive_path}")
        else:
            content = fetch(evidence.url)
            if _sha256(content) != evidence.sha256:
                raise EvidenceArchiveError(
                    f"evidence content does not match configured hash: {evidence.url}"
                )
            write_immutable(archive_path, content)
        archive_paths.append(archive_path)
    return tuple(archive_paths)


def _fetch_evidence_bytes(url: str) -> bytes:
    """Download one official evidence document with a bounded timeout."""
    request = Request(url, headers={"User-Agent": "quant-stack-evidence/1.0"})
    try:
        with urlopen(request, timeout=30) as response:
            return bytes(response.read())
    except OSError as error:
        raise EvidenceArchiveError(f"unable to fetch non-trading evidence: {url}") from error


def _fetch_evidence_with_receipt(url: str) -> CapturedEvidence:
    """Download one official source body and retain response metadata for provenance."""
    request = Request(url, headers={"User-Agent": "quant-stack-evidence/1.0"})
    try:
        with urlopen(request, timeout=30) as response:
            return CapturedEvidence(
                content=bytes(response.read()),
                http_metadata={
                    **{key.lower(): value for key, value in response.headers.items()},
                    ":status": str(response.status),
                },
                retrieved_at=datetime.now(UTC),
            )
    except OSError as error:
        raise EvidenceArchiveError(f"unable to fetch corporate-action evidence: {url}") from error


def _sha256(content: bytes) -> str:
    """Return the lowercase SHA-256 digest of immutable evidence content."""
    return sha256(content).hexdigest()
