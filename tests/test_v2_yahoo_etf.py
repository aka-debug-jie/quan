from __future__ import annotations

import json
from datetime import UTC, date, datetime
from decimal import Decimal
from pathlib import Path
from urllib.parse import urlparse

import pytest

from quant_stack_v2.yahoo_etf import (
    DEFAULT_YAHOO_ETF_SYMBOLS,
    YahooETFAdapter,
    YahooFetchPayload,
    YahooNetworkDisabled,
    load_yahoo_universe_report,
    parse_yahoo_payload,
    persist_yahoo_universe_report,
    snapshot_yahoo_symbol,
    snapshot_yahoo_universe,
)


def _response_payload(
    timestamps: list[int],
    closes: list[float | int | None],
    *,
    events: dict | None = None,
) -> bytes:
    chart = {
        "result": [
            {
                "timestamp": timestamps,
                "indicators": {
                    "adjclose": [{"adjclose": closes}],
                },
                "events": events or {},
            }
        ],
    }
    return json.dumps({"chart": chart, "error": None}).encode("utf-8")


def _symbol_from_url(url: str) -> str:
    parsed = urlparse(url)
    return parsed.path.rsplit("/", maxsplit=1)[-1]


def _offline_fetcher_factory(mapping: dict[str, bytes]):
    def _fetch(url: str):
        symbol = _symbol_from_url(url).split("?")[0]
        raw_bytes = mapping[symbol]
        return raw_bytes, {"x-foo": "bar"}, "200"

    return _fetch


def _adapter_from_payloads(payloads: dict[str, bytes], *, allow_network: bool = True):
    return YahooETFAdapter(
        allow_network=allow_network,
        fetcher=_offline_fetcher_factory(payloads),
    )


def test_snapshot_blocks_network_without_explicit_permission() -> None:
    adapter = YahooETFAdapter()
    with pytest.raises(YahooNetworkDisabled, match="network access is disallowed"):
        adapter.fetch("SPY")


def test_parse_adjusted_close_and_events() -> None:
    payload = YahooFetchPayload(
        symbol="SPY",
        source_url="https://query1.finance.yahoo.com/v8/finance/chart/SPY?range=max",
        canonical_request="events=div%2Csplit&includeAdjustedClose=true",
        request_parameters={"events": "div,split", "range": "max"},
        retrieved_at=datetime(2024, 1, 3, tzinfo=UTC),
        raw_bytes=_response_payload(
            [1704067200, 1704153600],
            [100.0, 110.0],
            events={
                "dividends": {
                    "1704153600": {"amount": "1.2", "date": 1704153600},
                },
                "splits": {
                    "1704230000": {
                        "numerator": "3",
                        "denominator": "2",
                        "date": 1704230000,
                    },
                },
            },
        ),
        http_metadata={"content-type": "application/json", ":status": "200"},
        raw_sha256="0" * 64,
    )

    bars, events, anomalies = parse_yahoo_payload(payload)

    assert anomalies == ()
    assert [bar.trading_date for bar in bars] == [date(2024, 1, 1), date(2024, 1, 2)]
    assert bars[0].adjusted_close == Decimal("100")
    assert {event.event_type for event in events} == {"dividend", "split"}
    assert {Decimal("1.2"), Decimal("1.5")} == {event.value for event in events}


def test_snapshot_symbol_persists_content_addressed_artifacts(tmp_path: Path) -> None:
    payloads = {
        "SPY": _response_payload(
            [1704067200],
            [111.0],
            events={"splits": {}},
        ),
    }
    adapter = _adapter_from_payloads(payloads, allow_network=True)
    data_root = tmp_path / "data" / "external"
    snapshot = snapshot_yahoo_symbol("SPY", data_root, adapter=adapter)

    manifest_path = (
        data_root
        / "yahoo_global_etf_research_v1"
        / snapshot.manifest.raw_sha256
        / "manifests"
        / f"{snapshot.manifest.manifest_id}.json"
    )
    root = data_root / "yahoo_global_etf_research_v1"
    raw_path = root / snapshot.manifest.raw_file.relative_path
    normalized_path = root / snapshot.manifest.normalized_file.relative_path

    assert manifest_path.is_file()
    assert raw_path.is_file()
    assert normalized_path.is_file()
    assert snapshot.manifest.row_count == 1
    assert snapshot.manifest.event_count == 0
    assert snapshot.manifest.raw_file.size_bytes == len(payloads["SPY"])
    assert snapshot.adjusted_bars[0].trading_date == date(2024, 1, 1)


def test_snapshot_universe_reports_common_dates_and_per_symbol_anomalies(tmp_path: Path) -> None:
    spy_payload = _response_payload([1704067200, 1704153600], [101.0, 102.0])
    mchi_payload = _response_payload([1704067200], [99.0])
    bil_payload = _response_payload([1704067200, 1704230000], [10.0, None])
    adapter = _adapter_from_payloads(
        {"SPY": spy_payload, "MCHI": mchi_payload, "BIL": bil_payload},
        allow_network=True,
    )
    report = snapshot_yahoo_universe(
        tmp_path / "data" / "external",
        symbols=("SPY", "MCHI", "BIL"),
        adapter=adapter,
        allow_network=True,
    )

    assert report.common_trading_dates == (date(2024, 1, 1),)
    assert any(item.kind == "missing_adjusted_close" for item in report.anomalies)
    assert any(snapshot.manifest.symbol == "SPY" for snapshot in report.symbol_snapshots)
    assert len(report.symbol_snapshots) == 3


def test_persisted_yahoo_report_loads_without_network(tmp_path: Path) -> None:
    payload = _response_payload([1704067200, 1704153600], [101.0, 102.0])
    root = tmp_path / "data" / "external"
    report = snapshot_yahoo_universe(
        root,
        symbols=("SPY",),
        adapter=_adapter_from_payloads({"SPY": payload}),
        allow_network=True,
    )
    path = persist_yahoo_universe_report(report, root)
    loaded = load_yahoo_universe_report(path)
    assert loaded.identity_sha256 == report.identity_sha256
    assert loaded.symbol_snapshots[0].adjusted_bars == report.symbol_snapshots[0].adjusted_bars


def test_snapshot_respects_fixed_default_universe() -> None:
    assert DEFAULT_YAHOO_ETF_SYMBOLS == (
        "MCHI",
        "SPY",
        "EFA",
        "IEF",
        "GLD",
        "DBC",
        "BIL",
    )


def test_snapshot_reports_adapter_failure_as_anomaly(tmp_path: Path) -> None:
    adapter = YahooETFAdapter(allow_network=False)
    with pytest.raises(YahooNetworkDisabled):
        snapshot_yahoo_symbol("SPY", tmp_path / "data" / "external", adapter=adapter)

    report = snapshot_yahoo_universe(
        tmp_path / "data" / "external",
        symbols=("SPY",),
        adapter=adapter,
        allow_network=False,
    )
    assert len(report.symbol_snapshots) == 0
    assert report.common_trading_dates == ()
    assert any(item.kind == "snapshot_failed" for item in report.anomalies)
