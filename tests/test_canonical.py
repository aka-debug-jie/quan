from datetime import date
from decimal import Decimal

import pytest

from quant_stack.data.canonical import (
    CanonicalizationError,
    derive_qfq_bars,
    persist_canonical_dataset,
    persist_canonical_raw_dataset,
)
from quant_stack.data.evidence import corporate_action_evidence_archive_path
from quant_stack.data.models import (
    CorporateActionEvent,
    CorporateActionKind,
    CorporateActionLedger,
    ETFUniverseInstrument,
    OfficialEvidence,
    ProviderId,
    ProviderSeriesManifest,
)
from quant_stack.models import DailyBar, Exchange, ManifestFile, PriceBasis


def instrument() -> ETFUniverseInstrument:
    return ETFUniverseInstrument(
        symbol="159919", exchange=Exchange.SZSE, effective_from=date(2015, 1, 1)
    )


def raw_bars() -> list[DailyBar]:
    return [
        DailyBar(
            symbol="159919",
            exchange=Exchange.SZSE,
            price_basis=PriceBasis.RAW,
            trading_date=date(2024, 1, 2),
            open=Decimal("10"),
            high=Decimal("10"),
            low=Decimal("10"),
            close=Decimal("10"),
            volume=Decimal("100"),
        ),
        DailyBar(
            symbol="159919",
            exchange=Exchange.SZSE,
            price_basis=PriceBasis.RAW,
            trading_date=date(2024, 1, 3),
            open=Decimal("5"),
            high=Decimal("5"),
            low=Decimal("5"),
            close=Decimal("5"),
            volume=Decimal("200"),
        ),
    ]


def evidence() -> OfficialEvidence:
    return OfficialEvidence(
        url="https://example.invalid/action.pdf", sha256="a" * 64, published_on=date(2024, 1, 3)
    )


def test_split_ledger_deterministically_reconstructs_qfq_ohlc() -> None:
    ledger = CorporateActionLedger(
        ledger_id="test",
        version=1,
        instrument=instrument(),
        completeness="complete",
        events=(
            CorporateActionEvent(
                effective_date=date(2024, 1, 3),
                kind=CorporateActionKind.SHARE_SPLIT,
                split_ratio=Decimal("2"),
                evidence=evidence(),
            ),
        ),
    )

    qfq, factors = derive_qfq_bars(raw_bars(), ledger)

    assert qfq[0].close == Decimal("5")
    assert qfq[1].close == Decimal("5")
    assert factors[0].factor == Decimal("0.5")
    assert factors[1].factor == Decimal("1")


def test_incomplete_ledger_cannot_generate_qfq() -> None:
    ledger = CorporateActionLedger(
        ledger_id="test", version=1, instrument=instrument(), completeness="incomplete"
    )

    with pytest.raises(CanonicalizationError, match="ledger must be complete"):
        derive_qfq_bars(raw_bars(), ledger)


def test_raw_canonical_publication_does_not_require_qfq_ledger(tmp_path) -> None:
    source = ProviderSeriesManifest(
        manifest_id="c" * 64,
        provider=ProviderId.SINA,
        instrument=instrument(),
        price_basis=PriceBasis.RAW,
        source_url="https://example.invalid/history",
        retrieved_at="2024-01-04T00:00:00+00:00",
        request_parameters={},
        http_metadata={},
        parser_version="1",
        normalization_version="1",
        raw_file=ManifestFile(relative_path="raw", sha256="a" * 64, size_bytes=1),
        normalized_file=ManifestFile(relative_path="normalized", sha256="b" * 64, size_bytes=1),
        row_count=2,
        first_trading_date=date(2024, 1, 2),
        last_trading_date=date(2024, 1, 3),
    )

    manifest = persist_canonical_raw_dataset(source, raw_bars(), tmp_path)

    assert manifest.price_basis is PriceBasis.RAW
    assert (tmp_path / manifest.output_file.relative_path).is_file()


def test_split_on_documented_non_trading_day_applies_before_next_raw_session() -> None:
    bars = raw_bars()
    bars[0] = bars[0].model_copy(update={"trading_date": date(2019, 1, 10)})
    bars[1] = bars[1].model_copy(update={"trading_date": date(2019, 1, 14)})
    ledger = CorporateActionLedger(
        ledger_id="test",
        version=1,
        instrument=instrument(),
        completeness="complete",
        events=(
            CorporateActionEvent(
                effective_date=date(2019, 1, 11),
                kind=CorporateActionKind.SHARE_SPLIT,
                split_ratio=Decimal("2"),
                evidence=evidence(),
            ),
        ),
    )

    qfq, factors = derive_qfq_bars(bars, ledger)

    assert qfq[0].close == Decimal("5")
    assert factors[0].factor == Decimal("0.5")


def test_complete_ledger_and_same_raw_snapshot_reproduce_canonical_artifacts(tmp_path) -> None:
    source_body = b"official action"
    action_evidence = OfficialEvidence(
        url="https://example.invalid/action.pdf",
        sha256="eeb6325e0a873b3dcdf7a21b0420be47565944e3b2fc7bd26bef4996d2da3e6a",
        published_on=date(2024, 1, 3),
    )
    corporate_action_evidence_archive_path(tmp_path, action_evidence).parent.mkdir(parents=True)
    corporate_action_evidence_archive_path(tmp_path, action_evidence).write_bytes(source_body)
    ledger = CorporateActionLedger(
        ledger_id="test-ledger",
        version=1,
        instrument=instrument(),
        completeness="complete",
        events=(
            CorporateActionEvent(
                effective_date=date(2024, 1, 3),
                kind=CorporateActionKind.SHARE_SPLIT,
                split_ratio=Decimal("2"),
                evidence=action_evidence,
            ),
        ),
    )
    provider_manifest = ProviderSeriesManifest(
        manifest_id="c" * 64,
        provider=ProviderId.SZSE_OFFICIAL,
        instrument=instrument(),
        price_basis=PriceBasis.RAW,
        source_url="https://example.invalid/history",
        retrieved_at="2024-01-04T00:00:00+00:00",
        request_parameters={},
        http_metadata={},
        parser_version="1",
        normalization_version="1",
        raw_file=ManifestFile(relative_path="raw", sha256="a" * 64, size_bytes=1),
        normalized_file=ManifestFile(relative_path="normalized", sha256="b" * 64, size_bytes=1),
        row_count=2,
        first_trading_date=date(2024, 1, 2),
        last_trading_date=date(2024, 1, 3),
    )

    first = persist_canonical_dataset(provider_manifest, raw_bars(), ledger, tmp_path)
    second = persist_canonical_dataset(provider_manifest, raw_bars(), ledger, tmp_path)

    assert first == second
    assert (tmp_path / first.raw_manifest.output_file.relative_path).is_file()
    assert (tmp_path / first.qfq_manifest.output_file.relative_path).is_file()
