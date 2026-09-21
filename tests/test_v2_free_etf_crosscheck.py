"""Offline contract tests for the global ETF free-source crosscheck."""

import json
from datetime import UTC, datetime
from hashlib import sha256
from pathlib import Path
from typing import Any

import pytest

from quant_stack_v2.free_etf_crosscheck import (
    COMPLETE,
    CONFLICT,
    FreeETFCrosscheckError,
    capture_sources,
    crosscheck,
    initialize_normalization_templates,
    load_config,
)

SYMBOLS = ("SPY", "GLD", "BIL", "EFA", "IEF", "MCHI", "DBC")
ISSUERS = {
    "SPY": "STATE_STREET",
    "GLD": "STATE_STREET",
    "BIL": "STATE_STREET",
    "EFA": "ISHARES",
    "IEF": "ISHARES",
    "MCHI": "ISHARES",
    "DBC": "INVESCO",
}
URLS = (
    "https://www.nyse.com/trade/hours-calendars",
    "https://www.ssga.com/us/en/individual/resources/documents/etf-dividend-distributions",
    "https://www.ssga.com/us/en/individual/etfs/spdr-gold-shares-gld",
    "https://www.ishares.com/us/library/financial-legal-tax",
    "https://www.invesco.com/us/en/accounts/tax-center/etf-tax-center.html",
)


def _config() -> dict[str, Any]:
    return {
        "schema_version": 1,
        "dataset_id": "yahoo_global_etf_research_v1",
        "window": {"start": "2025-01-01", "end": "2026-09-10"},
        "universe": [
            {"symbol": symbol, "issuer": ISSUERS[symbol], "exchange": "NYSE_ARCA"}
            for symbol in SYMBOLS
        ],
        "sources": [{"id": f"source_{index}", "url": url} for index, url in enumerate(URLS)],
        "forbidden_uses": ["execution", "backtest", "paper_broker", "promotion", "live_order"],
    }


def _raw(with_event: bool = False) -> bytes:
    timestamp = int(datetime(2025, 1, 2, tzinfo=UTC).timestamp())
    events: dict[str, Any] = {}
    if with_event:
        events = {"dividends": {"one": {"date": timestamp, "amount": "1.0"}}}
    return json.dumps(
        {
            "chart": {
                "result": [
                    {
                        "timestamp": [timestamp],
                        "indicators": {
                            "quote": [
                                {"open": [1], "high": [2], "low": [1], "close": [2], "volume": [3]}
                            ]
                        },
                        "events": events,
                    }
                ]
            }
        }
    ).encode()


def _inputs(
    tmp_path: Path, *, provider_event: bool = False
) -> tuple[dict[str, Any], Path, Path, Path, Path, Path, Path]:
    config = _config()
    source_root = tmp_path / "data/external/free"
    source_records: list[dict[str, str]] = []
    for source in config["sources"]:
        body = source["id"].encode()
        digest = sha256(body).hexdigest()
        path = source_root / "source_bodies" / digest / "body.bin"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(body)
        source_records.append({"id": source["id"], "url": source["url"], "sha256": digest})
    source_capture = tmp_path / "source_capture.json"
    source_capture.write_text(
        json.dumps({"kind": "v2_global_etf_usd_free_source_capture", "sources": source_records})
    )
    source_sha = source_records[0]["sha256"]
    yahoo_root = tmp_path / "data/external/yahoo"
    for symbol in SYMBOLS:
        raw = _raw(provider_event and symbol == "SPY")
        digest = sha256(raw).hexdigest()
        raw_path = yahoo_root / digest / "raw/response.json"
        raw_path.parent.mkdir(parents=True, exist_ok=True)
        raw_path.write_bytes(raw)
        manifest_path = yahoo_root / digest / "manifests" / f"{symbol}.json"
        manifest_path.parent.mkdir(parents=True, exist_ok=True)
        manifest_path.write_text(
            json.dumps(
                {
                    "symbol": symbol,
                    "raw_file": {
                        "relative_path": str(raw_path.relative_to(yahoo_root)),
                        "sha256": digest,
                    },
                }
            )
        )
    calendar = tmp_path / "data/external/calendar.json"
    calendar.write_text(
        json.dumps(
            {
                "kind": "v2_nyse_arca_calendar",
                "coverage": config["window"],
                "source_sha256": source_sha,
                "sessions": ["2025-01-02"],
            }
        )
    )
    universe = tmp_path / "data/external/universe.json"
    universe.parent.mkdir(parents=True, exist_ok=True)
    universe.write_text(
        json.dumps(
            {
                "kind": "v2_global_etf_static_universe",
                "instruments": [
                    {
                        "symbol": symbol,
                        "issuer": ISSUERS[symbol],
                        "exchange": "NYSE_ARCA",
                        "listing_date": "2000-01-01",
                        "source_sha256": source_sha,
                    }
                    for symbol in SYMBOLS
                ],
            }
        )
    )
    actions = tmp_path / "data/external/actions.json"
    actions.write_text(
        json.dumps(
            {
                "kind": "v2_global_etf_issuer_actions",
                "coverage": config["window"],
                "symbol_source_sha256": {symbol: source_sha for symbol in SYMBOLS},
                "events": [],
            }
        )
    )
    return config, yahoo_root, calendar, actions, universe, source_capture, source_root


def test_crosscheck_is_complete_but_never_execution_qualified(tmp_path: Path) -> None:
    inputs = _inputs(tmp_path)
    result = crosscheck(*inputs)
    assert result["status"] == COMPLETE
    assert result["provider_complete_session_count"] == 1
    assert result["FORMAL_RESEARCH_STATUS"] == "BLOCKED_DATA"


def test_crosscheck_preserves_event_conflict(tmp_path: Path) -> None:
    inputs = _inputs(tmp_path, provider_event=True)
    result = crosscheck(*inputs)
    assert result["status"] == CONFLICT
    assert result["missing_official_events"] == 1


def test_crosscheck_rejects_tampered_source_and_invalid_capture(tmp_path: Path) -> None:
    config, _, calendar, actions, universe, capture, source_root = _inputs(tmp_path)
    body = next(source_root.glob("source_bodies/*/body.bin"))
    body.write_bytes(b"tampered")
    with pytest.raises(FreeETFCrosscheckError, match="SHA-256"):
        crosscheck(
            config,
            tmp_path / "data/external/yahoo",
            calendar,
            actions,
            universe,
            capture,
            source_root,
        )
    with pytest.raises(FreeETFCrosscheckError, match="allow-network"):
        capture_sources(config, source_root, allow_network=False)


def test_config_rejects_non_frozen_window(tmp_path: Path) -> None:
    path = tmp_path / "config.yaml"
    value = _config()
    value["window"] = {"start": "2024-01-01", "end": "2026-09-10"}
    path.write_text(json.dumps(value))
    with pytest.raises(FreeETFCrosscheckError, match="window"):
        load_config(path)


def test_normalization_templates_are_source_bound_and_not_crosscheck_inputs(tmp_path: Path) -> None:
    config, _, _, _, _, capture, source_root = _inputs(tmp_path)
    identities = initialize_normalization_templates(
        config, capture, source_root / "normalization_templates"
    )
    assert set(identities) == {
        "calendar_template_sha256",
        "issuer_actions_template_sha256",
        "universe_template_sha256",
    }
    calendar = next((source_root / "normalization_templates/calendar_templates").glob("*.json"))
    assert "template_not_input" in calendar.read_text()
