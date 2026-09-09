from datetime import UTC, date, datetime
from pathlib import Path

import pytest

from quant_stack.data.models import ETFHistoryRequest, ETFUniverseInstrument, PriceBasis
from quant_stack.data.sina_etf import (
    SinaHistoryPayload,
    SinaProviderError,
    load_sina_provider_bars,
    parse_sina_etf_history,
    persist_sina_etf_history,
)
from quant_stack.models import Exchange

FIXTURE = Path(__file__).parent / "fixtures" / "sina" / "159919_history.js"


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


def payload() -> SinaHistoryPayload:
    return SinaHistoryPayload(
        source_url="https://finance.sina.com.cn/realstock/company/sz159919/hisdata_klc2/klc_kl.js",
        request_parameters={"symbol": "sz159919"},
        http_metadata={":status": "200", "content-type": "application/javascript"},
        retrieved_at=datetime(2024, 1, 5, tzinfo=UTC),
        raw_bytes=FIXTURE.read_bytes(),
    )


def decoded_rows(_: bytes) -> list[dict[str, str]]:
    return [
        {
            "date": "2024-01-02T00:00:00.000Z",
            "open": "10",
            "high": "10.2",
            "low": "9.8",
            "close": "10",
            "volume": "1000",
        },
        {
            "date": "2024-01-03",
            "open": "5.1",
            "high": "5.2",
            "low": "4.9",
            "close": "5",
            "volume": "2000",
        },
        {
            "date": "2024-01-04",
            "open": "5",
            "high": "5.2",
            "low": "4.9",
            "close": "5.1",
            "volume": "1500",
        },
    ]


def test_maps_decoded_sina_rows_to_independent_raw_bars() -> None:
    bars = parse_sina_etf_history(request(), payload(), decoded_rows)

    assert [bar.trading_date for bar in bars] == [
        date(2024, 1, 2),
        date(2024, 1, 3),
        date(2024, 1, 4),
    ]
    assert all(bar.price_basis is PriceBasis.RAW for bar in bars)
    assert bars[1].close == 5


def test_rejects_adjusted_sina_request() -> None:
    with pytest.raises(SinaProviderError, match="raw daily bars only"):
        parse_sina_etf_history(request(PriceBasis.QFQ), payload(), decoded_rows)


def test_persists_hash_verified_provider_native_sina_artifacts(tmp_path: Path) -> None:
    manifest = persist_sina_etf_history(request(), payload(), tmp_path, decoded_rows)

    assert manifest.provider.value == "sina"
    assert manifest.request_parameters == {"symbol": "sz159919"}
    assert (tmp_path / manifest.raw_file.relative_path).read_bytes() == FIXTURE.read_bytes()
    assert len(load_sina_provider_bars(manifest, tmp_path)) == 3


def test_reuses_stable_manifest_for_identical_sina_content(tmp_path: Path) -> None:
    first = persist_sina_etf_history(request(), payload(), tmp_path, decoded_rows)
    retry = persist_sina_etf_history(request(), payload(), tmp_path, decoded_rows)

    assert retry.manifest_id == first.manifest_id
    assert retry.retrieved_at == first.retrieved_at
