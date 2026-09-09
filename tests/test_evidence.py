from datetime import UTC, date, datetime
from hashlib import sha256
from pathlib import Path

import pytest

from quant_stack.data.evidence import (
    CapturedEvidence,
    EvidenceArchiveError,
    archive_corporate_action_source,
    capture_non_trading_evidence,
    require_non_trading_evidence,
)
from quant_stack.data.ingest import load_etf_universe
from quant_stack.data.models import DocumentedNonTradingEvent, OfficialEvidence


def event(content: bytes = b"official-evidence") -> DocumentedNonTradingEvent:
    return DocumentedNonTradingEvent(
        dates=(date(2015, 4, 13), date(2015, 4, 14)),
        reason="fund share conversion suspension",
        evidence=OfficialEvidence(
            url="https://example.invalid/evidence.pdf",
            sha256=sha256(content).hexdigest(),
            published_on=date(2015, 4, 13),
        ),
    )


def test_non_trading_evidence_requires_local_hash_verified_body(tmp_path: Path) -> None:
    documented_event = event()
    with pytest.raises(EvidenceArchiveError, match="missing local"):
        require_non_trading_evidence((documented_event,), tmp_path)

    paths = capture_non_trading_evidence(
        (documented_event,),
        tmp_path,
        fetcher=lambda _: b"official-evidence",
    )

    assert len(paths) == 1
    require_non_trading_evidence((documented_event,), tmp_path)


def test_non_trading_evidence_rejects_hash_mismatch(tmp_path: Path) -> None:
    documented_event = event()
    with pytest.raises(EvidenceArchiveError, match="does not match configured hash"):
        capture_non_trading_evidence(
            (documented_event,),
            tmp_path,
            fetcher=lambda _: b"altered-evidence",
        )


def test_archives_corporate_action_source_with_first_http_receipt(tmp_path: Path) -> None:
    evidence = archive_corporate_action_source(
        "https://example.invalid/action.pdf",
        tmp_path,
        fetcher=lambda _: CapturedEvidence(
            content=b"official-action",
            http_metadata={":status": "200"},
            retrieved_at=datetime(2024, 1, 3, tzinfo=UTC),
        ),
    )

    body = tmp_path / "raw" / "corporate_action_evidence" / evidence.sha256 / "evidence.bin"
    assert body.read_bytes() == b"official-action"
    assert (body.parent / "receipt.json").is_file()


def test_non_trading_event_rejects_duplicate_dates() -> None:
    with pytest.raises(ValueError, match="unique and sorted"):
        DocumentedNonTradingEvent(
            dates=(date(2015, 4, 13), date(2015, 4, 13)),
            reason="duplicate",
            evidence=OfficialEvidence(
                url="https://example.invalid/evidence.pdf",
                sha256="a" * 64,
                published_on=date(2015, 4, 13),
            ),
        )


def test_v2_universe_declares_verified_510500_non_trading_dates() -> None:
    universe = load_etf_universe(
        Path(__file__).parents[1] / "configs" / "assets" / "etf_universe_v2.yaml"
    )
    instruments = {instrument.symbol: instrument for instrument in universe.instruments}

    assert universe.universe_id == "cn_etf_smoke_v2"
    assert universe.version == 2
    assert set(instruments) == {"510300", "510500", "159919"}
    assert instruments["510500"].documented_non_trading_events[0].dates == (
        date(2015, 4, 13),
        date(2015, 4, 14),
    )
    assert instruments["159919"].documented_non_trading_events[0].dates == (date(2019, 1, 11),)
