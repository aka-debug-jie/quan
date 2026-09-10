from datetime import date
from decimal import Decimal
from hashlib import sha256
from pathlib import Path

from quant_stack.d0_inventory import build_event_inventory, persist_event_inventory
from quant_stack.data.models import (
    CorporateActionEvent,
    CorporateActionKind,
    CorporateActionLedger,
    D0CandidateClassification,
    D0SourceSelection,
    OfficialEvidence,
)
from quant_stack.models import DailyBar, Exchange, Instrument, PriceBasis


def _bar(trading_date: date, close: str) -> DailyBar:
    return DailyBar(
        symbol="159919",
        exchange=Exchange.SZSE,
        price_basis=PriceBasis.RAW,
        trading_date=trading_date,
        open=Decimal(close),
        high=Decimal(close),
        low=Decimal(close),
        close=Decimal(close),
        volume=Decimal("1"),
    )


def _selection(body: bytes, complete: bool) -> D0SourceSelection:
    return D0SourceSelection(
        symbol="159919",
        exchange=Exchange.SZSE,
        canonical_raw_manifest_id="a" * 64,
        cross_check_manifest_id="b" * 64,
        adjustment_candidate_sha256=sha256(body).hexdigest(),
        official_inventory_complete=complete,
    )


def _ledger(status: str = "official_evidence_chain_verified") -> CorporateActionLedger:
    evidence = OfficialEvidence(
        url="https://example.invalid/action.pdf",
        sha256="c" * 64,
        published_on=date(2024, 1, 2),
    )
    return CorporateActionLedger(
        ledger_id="test",
        version=1,
        instrument=Instrument(symbol="159919", exchange=Exchange.SZSE),
        completeness="incomplete",
        events=(
            CorporateActionEvent(
                effective_date=date(2024, 1, 2),
                kind=CorporateActionKind.SHARE_SPLIT,
                split_ratio=Decimal("1.110680861"),
                evidence=evidence,
                availability_evidence=evidence if status != "candidate" else None,
                value_evidence=evidence if status != "candidate" else None,
                verification_status=status,
            ),
        ),
    )


def _archive_candidate(root: Path, body: bytes) -> None:
    digest = sha256(body).hexdigest()
    path = root / "raw" / "sina_adjustment" / digest / "response.js"
    path.parent.mkdir(parents=True)
    path.write_bytes(body)


def test_inventory_matches_provider_ratio_at_official_decimal_precision(tmp_path: Path) -> None:
    body = (
        b'var sh510500hfq={"data":['
        b'{"d":"2024-01-02","s":"0.4245239277782239","u":"0"},'
        b'{"d":"2023-01-02","s":"0.3822195400000000","u":"0"}]}'
    )
    _archive_candidate(tmp_path, body)

    report = build_event_inventory(
        _selection(body, True),
        _ledger(),
        [_bar(date(2024, 1, 1), "10"), _bar(date(2024, 1, 2), "5")],
        tmp_path,
    )

    assert report.inventory_complete
    assert report.unexplained_count == 0
    assert report.rows[0].classification is D0CandidateClassification.VERIFIED_SPLIT_OR_CONVERSION


def test_inventory_never_promotes_candidate_or_unattested_official_scan(tmp_path: Path) -> None:
    body = (
        b'var sh510500hfq={"data":['
        b'{"d":"2024-01-02","s":"0.4245239277782239","u":"0"},'
        b'{"d":"2023-01-02","s":"0.3822195400000000","u":"0"}]}'
    )
    _archive_candidate(tmp_path, body)

    report = build_event_inventory(
        _selection(body, False),
        _ledger("candidate"),
        [_bar(date(2024, 1, 1), "10"), _bar(date(2024, 1, 2), "5")],
        tmp_path,
    )

    assert not report.inventory_complete
    assert report.unexplained_count == 1
    assert persist_event_inventory(report, tmp_path / "artifacts").is_file()
