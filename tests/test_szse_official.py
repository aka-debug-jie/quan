from dataclasses import replace
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from pathlib import Path

import pytest

from quant_stack.data.models import ETFHistoryRequest, ETFUniverseInstrument, PriceBasis
from quant_stack.data.szse_official import (
    SZSEHistoryPayload,
    SZSEProviderError,
    load_szse_provider_bars,
    parse_szse_daily_history,
    persist_szse_daily_history,
    reattest_szse_daily_history,
)
from quant_stack.models import Exchange

FIXTURE = Path(__file__).parent / "fixtures" / "szse" / "159919_history.json"


def request(price_basis: PriceBasis = PriceBasis.RAW) -> ETFHistoryRequest:
    return ETFHistoryRequest(
        instrument=ETFUniverseInstrument(
            symbol="159919",
            exchange=Exchange.SZSE,
            effective_from=date(2015, 1, 1),
        ),
        universe_id="test-v2",
        universe_version=2,
        start_date=date(2024, 1, 2),
        as_of_date=date(2024, 1, 4),
        price_basis=price_basis,
    )


def payload() -> SZSEHistoryPayload:
    return SZSEHistoryPayload(
        source_url="https://www.szse.cn/api/market/ssjjhq/getHistoryData?cycleType=32",
        request_parameters={"cycleType": "32", "marketId": "1", "code": "159919"},
        http_metadata={"content-type": "application/json", "etag": "fixture"},
        retrieved_at=datetime(2024, 1, 5, tzinfo=UTC),
        raw_bytes=FIXTURE.read_bytes(),
    )


def test_parses_official_szse_kline_array_in_documented_field_order() -> None:
    bars = parse_szse_daily_history(request(), payload())

    assert [bar.trading_date for bar in bars] == [
        date(2024, 1, 2),
        date(2024, 1, 3),
        date(2024, 1, 4),
    ]
    assert bars[0].open == 10
    assert bars[0].close == 10
    assert bars[1].low == Decimal("4.9")
    assert bars[1].high == Decimal("5.2")
    assert bars[1].volume == 2000


def test_rejects_qfq_request_for_raw_only_szse_provider() -> None:
    with pytest.raises(SZSEProviderError, match="raw daily bars only"):
        parse_szse_daily_history(request(PriceBasis.QFQ), payload())


def test_persists_provider_native_json_and_manifest_without_canonicalization(
    tmp_path: Path,
) -> None:
    manifest = persist_szse_daily_history(request(), payload(), tmp_path)

    assert manifest.provider.value == "szse_official"
    assert manifest.request_parameters["code"] == "159919"
    assert manifest.http_metadata["etag"] == "fixture"
    assert (tmp_path / manifest.raw_file.relative_path).read_bytes() == FIXTURE.read_bytes()
    bars = load_szse_provider_bars(manifest, tmp_path)
    assert len(bars) == 3
    assert bars[0].price_basis is PriceBasis.RAW


def test_identical_provider_content_reuses_first_receipt_without_timestamp_in_identity(
    tmp_path: Path,
) -> None:
    first = persist_szse_daily_history(request(), payload(), tmp_path)
    retry = persist_szse_daily_history(
        request(),
        replace(payload(), retrieved_at=payload().retrieved_at + timedelta(minutes=1)),
        tmp_path,
    )

    assert retry.manifest_id == first.manifest_id
    assert retry.retrieved_at == first.retrieved_at


def test_reattests_retained_raw_response_without_network_access(tmp_path: Path) -> None:
    original = persist_szse_daily_history(request(), payload(), tmp_path)

    reattested = reattest_szse_daily_history(request(), original, tmp_path)

    assert reattested.manifest_id == original.manifest_id
    assert reattested.volume_unit == "lots"
