import json
from datetime import UTC, date, datetime
from decimal import Decimal
from pathlib import Path

import pytest

from quant_stack.data.models import ETFHistoryRequest, ETFUniverseInstrument
from quant_stack.data.sina_etf import SinaHistoryPayload
from quant_stack.data.sse_official import (
    SSEProviderError,
    load_sse_provider_bars,
    parse_sse_daily_history,
    persist_sse_daily_history,
)
from quant_stack.models import Exchange, PriceBasis


def _request(exchange: Exchange = Exchange.SSE) -> ETFHistoryRequest:
    return ETFHistoryRequest(
        instrument=ETFUniverseInstrument(
            symbol="510300", exchange=exchange, effective_from=date(2015, 1, 1)
        ),
        start_date=date(2024, 1, 2),
        as_of_date=date(2024, 1, 3),
        price_basis=PriceBasis.RAW,
    )


def _payload() -> SinaHistoryPayload:
    return SinaHistoryPayload(
        source_url="https://yunhq.sse.com.cn:32042/v1/sh1/dayk/510300",
        request_parameters={"select": "date,open,high,low,close,volume"},
        http_metadata={":status": "200"},
        retrieved_at=datetime(2024, 1, 4, tzinfo=UTC),
        raw_bytes=(
            b'{"code":"510300","total":2,"begin":0,"end":2,"kline":'
            b"[[20240102,3.0,3.1,2.9,3.05,100],[20240103,3.05,3.2,3.0,3.1,200]]}"
        ),
    )


def test_parses_and_persists_sse_official_raw_without_adjustment(tmp_path: Path) -> None:
    manifest = persist_sse_daily_history(_request(), _payload(), tmp_path)

    bars = load_sse_provider_bars(manifest, tmp_path)

    assert manifest.provider.value == "sse_official"
    assert [bar.close for bar in bars] == [Decimal("3.05"), Decimal("3.1")]
    assert all(bar.price_basis is PriceBasis.RAW for bar in bars)


def test_rejects_non_sse_request() -> None:
    with pytest.raises(SSEProviderError, match="SSE raw ETF"):
        parse_sse_daily_history(_request(Exchange.SZSE), _payload())


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("code", "510500", "unexpected security"),
        ("total", 3, "not a complete series"),
    ],
)
def test_rejects_wrong_symbol_or_incomplete_sse_series(
    field: str, value: object, message: str
) -> None:
    payload = _payload()
    body = json.loads(payload.raw_bytes)
    body[field] = value
    invalid = SinaHistoryPayload(
        source_url=payload.source_url,
        request_parameters=payload.request_parameters,
        http_metadata=payload.http_metadata,
        retrieved_at=payload.retrieved_at,
        raw_bytes=json.dumps(body).encode(),
    )

    with pytest.raises(SSEProviderError, match=message):
        parse_sse_daily_history(_request(), invalid)
