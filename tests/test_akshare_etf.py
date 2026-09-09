from datetime import date
from decimal import Decimal
from pathlib import Path

import pandas as pd
import pytest

from quant_stack.data.akshare_etf import (
    AKShareETFAdapter,
    DataFetchError,
    NormalizationError,
    ProviderSchemaError,
    normalize_daily_bars,
    provider_export_bytes,
)
from quant_stack.data.models import ETFHistoryRequest, ETFUniverseInstrument
from quant_stack.models import Exchange, PriceBasis

FIXTURES = Path(__file__).parent / "fixtures" / "akshare"


def request(price_basis: PriceBasis = PriceBasis.RAW) -> ETFHistoryRequest:
    return ETFHistoryRequest(
        instrument=ETFUniverseInstrument(
            symbol="510300",
            exchange=Exchange.SSE,
            effective_from=date(2015, 1, 1),
        ),
        start_date=date(2024, 1, 2),
        as_of_date=date(2024, 1, 4),
        price_basis=price_basis,
    )


def raw_frame() -> pd.DataFrame:
    return pd.read_csv(FIXTURES / "etf_daily_raw.csv")


def test_normalizes_chinese_akshare_columns_and_retains_price_basis() -> None:
    bars = normalize_daily_bars(request(), raw_frame())

    assert [bar.trading_date for bar in bars] == [
        date(2024, 1, 2),
        date(2024, 1, 3),
        date(2024, 1, 4),
    ]
    assert bars[0].exchange is Exchange.SSE
    assert bars[0].price_basis is PriceBasis.RAW
    assert bars[0].close == Decimal("1.0100")


def test_raw_and_qfq_requests_stay_distinct() -> None:
    raw_bars = normalize_daily_bars(request(PriceBasis.RAW), raw_frame())
    qfq_bars = normalize_daily_bars(
        request(PriceBasis.QFQ), pd.read_csv(FIXTURES / "etf_daily_qfq.csv")
    )

    assert raw_bars[0].price_basis is PriceBasis.RAW
    assert qfq_bars[0].price_basis is PriceBasis.QFQ
    assert raw_bars[0].close != qfq_bars[0].close


def test_rejects_missing_provider_column() -> None:
    frame = raw_frame().drop(columns="成交量")
    with pytest.raises(ProviderSchemaError, match="成交量"):
        provider_export_bytes(frame)


def test_rejects_out_of_range_provider_date() -> None:
    frame = raw_frame()
    frame.loc[0, "日期"] = "2024-01-01"
    with pytest.raises(NormalizationError, match="outside requested interval"):
        normalize_daily_bars(request(), frame)


def test_retries_transient_provider_failure_once() -> None:
    calls = 0
    delays: list[float] = []

    def fetcher(_: ETFHistoryRequest) -> pd.DataFrame:
        nonlocal calls
        calls += 1
        if calls == 1:
            raise RuntimeError("temporary provider failure")
        return raw_frame()

    adapter = AKShareETFAdapter(
        fetcher, max_attempts=2, retry_delay_seconds=0.25, sleep_fn=delays.append
    )

    assert adapter.fetch(request()).equals(raw_frame())
    assert calls == 2
    assert delays == [0.25]


def test_raises_after_retry_budget_is_exhausted() -> None:
    adapter = AKShareETFAdapter(
        lambda _: (_ for _ in ()).throw(RuntimeError("unavailable")),
        max_attempts=2,
        sleep_fn=lambda _: None,
    )

    with pytest.raises(DataFetchError, match=r"failed after 2 attempts.*2024-01-02\.\.2024-01-04"):
        adapter.fetch(request())
