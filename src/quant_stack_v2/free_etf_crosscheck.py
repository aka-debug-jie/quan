"""Fail-closed free-source crosschecks for the frozen global ETF research audit."""

from __future__ import annotations

from datetime import UTC, date, datetime
from decimal import Decimal, InvalidOperation
from hashlib import sha256
from pathlib import Path
from time import sleep
from typing import Any, cast
from urllib.parse import urlparse
from urllib.request import Request, urlopen

import yaml

from quant_stack.snapshot import write_immutable
from quant_stack_v2.dev_contract import canonical, write_blob
from quant_stack_v2.free_etf_audit import RAW_FIELDS, _object, _regular_bytes

ALLOWED_HOSTS = {"www.nyse.com", "www.ssga.com", "www.ishares.com", "www.invesco.com"}
COMPLETE = "FREE_RESEARCH_CROSSCHECK_COMPLETE_NOT_EXECUTION_QUALIFIED"
CONFLICT = "FREE_RESEARCH_CROSSCHECK_CONFLICT_NOT_EXECUTION_QUALIFIED"


class FreeETFCrosscheckError(ValueError):
    """Raised when free crosscheck inputs are malformed, unpinned, or out of scope."""


def load_config(path: Path) -> dict[str, Any]:
    """Load the one frozen global-ETF crosscheck configuration."""
    try:
        value = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as error:
        raise FreeETFCrosscheckError("free crosscheck configuration is unreadable") from error
    if not isinstance(value, dict):
        raise FreeETFCrosscheckError("free crosscheck configuration must be a mapping")
    required = {"schema_version", "dataset_id", "window", "universe", "sources", "forbidden_uses"}
    if set(value) != required or value.get("schema_version") != 1:
        raise FreeETFCrosscheckError("free crosscheck configuration schema is invalid")
    if value.get("dataset_id") != "yahoo_global_etf_research_v1":
        raise FreeETFCrosscheckError("free crosscheck dataset differs from frozen Yahoo archive")
    window = value.get("window")
    universe = value.get("universe")
    sources = value.get("sources")
    if (
        not isinstance(window, dict)
        or not isinstance(universe, list)
        or not isinstance(sources, list)
    ):
        raise FreeETFCrosscheckError("free crosscheck configuration values are invalid")
    _window(window)
    _universe(universe)
    _sources(sources)
    return cast(dict[str, Any], value)


def capture_sources(
    config: dict[str, Any], data_root: Path, *, allow_network: bool
) -> dict[str, Any]:
    """Capture only configured public source bodies into content-addressed local storage."""
    if not allow_network:
        raise FreeETFCrosscheckError("--allow-network is required for free source capture")
    captured: list[dict[str, str]] = []
    for source in _sources(config["sources"]):
        body = _fetch(source["url"])
        digest = sha256(body).hexdigest()
        write_immutable(data_root / "source_bodies" / digest / "body.bin", body)
        captured.append({"id": source["id"], "url": source["url"], "sha256": digest})
    return {
        "schema_version": 1,
        "kind": "v2_global_etf_usd_free_source_capture",
        "dataset_id": config["dataset_id"],
        "sources": sorted(captured, key=lambda item: item["id"]),
        "status": "CAPTURE_COMPLETE_REQUIRES_OFFLINE_NORMALIZATION",
        "FORMAL_PIT_STATUS": "BLOCKED_DATA",
        "FORMAL_RESEARCH_STATUS": "BLOCKED_DATA",
        "CSI500": "NOT_STARTED",
    }


def persist_source_capture(result: dict[str, Any], artifact_root: Path) -> str:
    """Publish the configured-source capture receipt as a CAS JSON object."""
    return write_blob(artifact_root / "free_source_capture", canonical(result))


def initialize_normalization_templates(
    config: dict[str, Any], source_capture_path: Path, template_root: Path
) -> dict[str, str]:
    """Publish source-bound templates that are intentionally invalid as crosscheck inputs."""
    source_hashes = sorted(_source_hashes(source_capture_path, template_root.parent, config))
    start, end = _window(cast(dict[str, Any], config["window"]))
    universe = _universe(cast(list[Any], config["universe"]))
    coverage = {"start": start.isoformat(), "end": end.isoformat()}
    templates = {
        "calendar_template_sha256": write_blob(
            template_root / "calendar_templates",
            canonical(
                {
                    "schema_version": 1,
                    "kind": "v2_nyse_arca_calendar_template_not_input",
                    "coverage": coverage,
                    "required_source_sha256": source_hashes,
                    "required_fields": ["sessions", "source_sha256"],
                }
            ),
        ),
        "issuer_actions_template_sha256": write_blob(
            template_root / "issuer_action_templates",
            canonical(
                {
                    "schema_version": 1,
                    "kind": "v2_global_etf_issuer_actions_template_not_input",
                    "coverage": coverage,
                    "symbols": sorted(universe),
                    "required_source_sha256": source_hashes,
                    "required_fields": ["symbol_source_sha256", "events"],
                }
            ),
        ),
        "universe_template_sha256": write_blob(
            template_root / "universe_templates",
            canonical(
                {
                    "schema_version": 1,
                    "kind": "v2_global_etf_static_universe_template_not_input",
                    "coverage": coverage,
                    "universe": universe,
                    "required_source_sha256": source_hashes,
                    "required_fields": ["instruments"],
                }
            ),
        ),
    }
    return templates


def crosscheck(
    config: dict[str, Any],
    yahoo_root: Path,
    calendar_path: Path,
    issuer_actions_path: Path,
    universe_path: Path,
    source_capture_path: Path,
    source_root: Path,
) -> dict[str, Any]:
    """Compare archived Yahoo observations to pinned official-derived local inputs."""
    start, end = _window(cast(dict[str, Any], config["window"]))
    expected_universe = _universe(cast(list[Any], config["universe"]))
    source_hashes = _source_hashes(source_capture_path, source_root, config)
    calendar = _pinned_object(calendar_path, "calendar")
    actions = _pinned_object(issuer_actions_path, "issuer actions")
    universe = _pinned_object(universe_path, "universe")
    sessions = _calendar_sessions(calendar, start, end, source_hashes)
    _validate_universe(universe, expected_universe, start, source_hashes)
    official_events = _official_events(actions, expected_universe, start, end, source_hashes)
    provider_sessions, provider_events = _yahoo_observations(
        yahoo_root, expected_universe, start, end
    )
    missing_sessions = sorted(sessions - provider_sessions)
    unexpected_sessions = sorted(provider_sessions - sessions)
    missing_events = sorted(provider_events - official_events)
    unexpected_events = sorted(official_events - provider_events)
    status = (
        COMPLETE
        if not (missing_sessions or unexpected_sessions or missing_events or unexpected_events)
        else CONFLICT
    )
    return {
        "schema_version": 1,
        "kind": "v2_global_etf_usd_free_research_crosscheck",
        "status": status,
        "window": {"start": start.isoformat(), "end": end.isoformat()},
        "calendar_session_count": len(sessions),
        "provider_complete_session_count": len(provider_sessions),
        "missing_provider_sessions": len(missing_sessions),
        "unexpected_provider_sessions": len(unexpected_sessions),
        "provider_event_count": len(provider_events),
        "official_event_count": len(official_events),
        "missing_official_events": len(missing_events),
        "unexpected_official_events": len(unexpected_events),
        "source_capture_sha256": sha256(source_capture_path.read_bytes()).hexdigest(),
        "FORMAL_PIT_STATUS": "BLOCKED_DATA",
        "FORMAL_RESEARCH_STATUS": "BLOCKED_DATA",
        "CSI500": "NOT_STARTED",
        "forbidden_uses": ["execution", "backtest", "paper_broker", "promotion"],
    }


def persist_crosscheck(result: dict[str, Any], artifact_root: Path) -> str:
    """Persist one deterministic free-source crosscheck receipt."""
    return write_blob(artifact_root / "free_research_crosscheck", canonical(result))


def _window(value: dict[str, Any]) -> tuple[date, date]:
    try:
        start = date.fromisoformat(str(value["start"]))
        end = date.fromisoformat(str(value["end"]))
    except (KeyError, ValueError) as error:
        raise FreeETFCrosscheckError("crosscheck window is invalid") from error
    if start != date(2025, 1, 1) or end != date(2026, 9, 10):
        raise FreeETFCrosscheckError("crosscheck window differs from frozen free-audit scope")
    return start, end


def _universe(value: list[Any]) -> dict[str, dict[str, str]]:
    output: dict[str, dict[str, str]] = {}
    for item in value:
        if not isinstance(item, dict):
            raise FreeETFCrosscheckError("crosscheck universe record is invalid")
        symbol, issuer, exchange = item.get("symbol"), item.get("issuer"), item.get("exchange")
        if (
            not isinstance(symbol, str)
            or not symbol
            or not isinstance(issuer, str)
            or not issuer
            or not isinstance(exchange, str)
            or not exchange
        ):
            raise FreeETFCrosscheckError("crosscheck universe identity is invalid")
        if exchange != "NYSE_ARCA" or symbol in output:
            raise FreeETFCrosscheckError("crosscheck universe exchange or symbol is invalid")
        output[symbol] = {"issuer": issuer, "exchange": exchange}
    if set(output) != {"SPY", "GLD", "BIL", "EFA", "IEF", "MCHI", "DBC"}:
        raise FreeETFCrosscheckError("crosscheck universe differs from frozen seven ETFs")
    return output


def _sources(value: list[Any]) -> list[dict[str, str]]:
    output: list[dict[str, str]] = []
    for item in value:
        if (
            not isinstance(item, dict)
            or not isinstance(item.get("id"), str)
            or not isinstance(item.get("url"), str)
        ):
            raise FreeETFCrosscheckError("crosscheck source record is invalid")
        parsed = urlparse(item["url"])
        if parsed.scheme != "https" or parsed.netloc not in ALLOWED_HOSTS:
            raise FreeETFCrosscheckError("crosscheck source is not an approved public host")
        output.append({"id": item["id"], "url": item["url"]})
    if len({item["id"] for item in output}) != len(output) or len(output) < 5:
        raise FreeETFCrosscheckError(
            "crosscheck source plan must contain at least five unique sources"
        )
    return output


def _fetch(url: str) -> bytes:
    error: OSError | None = None
    for _ in range(3):
        try:
            with urlopen(
                Request(url, headers={"User-Agent": "quant-stack-free-audit/1.0"}), timeout=30
            ) as response:
                body = cast(bytes, response.read())
            if not body:
                raise OSError("empty response")
            return body
        except OSError as caught:
            error = caught
            sleep(1)
    raise FreeETFCrosscheckError(f"unable to capture configured public source: {url}") from error


def _pinned_object(path: Path, name: str) -> dict[str, Any]:
    return _object(_regular_bytes(path, 8 * 1024 * 1024), name)


def _source_hashes(path: Path, source_root: Path, config: dict[str, Any]) -> set[str]:
    capture = _pinned_object(path, "source capture")
    if capture.get("kind") != "v2_global_etf_usd_free_source_capture":
        raise FreeETFCrosscheckError("source capture kind is invalid")
    expected_urls = {item["url"] for item in _sources(cast(list[Any], config["sources"]))}
    records = capture.get("sources")
    if (
        not isinstance(records, list)
        or {item.get("url") for item in records if isinstance(item, dict)} != expected_urls
    ):
        raise FreeETFCrosscheckError("source capture differs from frozen source plan")
    hashes = {item.get("sha256") for item in records if isinstance(item, dict)}
    if not all(isinstance(item, str) and len(item) == 64 for item in hashes):
        raise FreeETFCrosscheckError("source capture hashes are invalid")
    for digest in hashes:
        if not isinstance(digest, str):
            raise FreeETFCrosscheckError("source capture hash is invalid")
        body = _regular_bytes(source_root / "source_bodies" / digest / "body.bin", 64 * 1024 * 1024)
        if sha256(body).hexdigest() != digest:
            raise FreeETFCrosscheckError("captured source body SHA-256 mismatch")
    return cast(set[str], hashes)


def _calendar_sessions(
    value: dict[str, Any], start: date, end: date, source_hashes: set[str]
) -> set[date]:
    if value.get("kind") != "v2_nyse_arca_calendar" or value.get("coverage") != {
        "start": start.isoformat(),
        "end": end.isoformat(),
    }:
        raise FreeETFCrosscheckError("official calendar scope is invalid")
    if (
        not isinstance(value.get("source_sha256"), str)
        or value["source_sha256"] not in source_hashes
    ):
        raise FreeETFCrosscheckError("official calendar is not bound to captured source")
    records = value.get("sessions")
    if not isinstance(records, list):
        raise FreeETFCrosscheckError("official calendar sessions are invalid")
    sessions = {date.fromisoformat(str(item)) for item in records}
    if (
        len(sessions) != len(records)
        or not sessions
        or min(sessions) < start
        or max(sessions) > end
    ):
        raise FreeETFCrosscheckError("official calendar dates are invalid")
    return sessions


def _validate_universe(
    value: dict[str, Any], expected: dict[str, dict[str, str]], start: date, source_hashes: set[str]
) -> None:
    if value.get("kind") != "v2_global_etf_static_universe":
        raise FreeETFCrosscheckError("static universe kind is invalid")
    records = value.get("instruments")
    if not isinstance(records, list):
        raise FreeETFCrosscheckError("static universe instruments are invalid")
    actual: dict[str, dict[str, str]] = {}
    for item in records:
        if not isinstance(item, dict):
            raise FreeETFCrosscheckError("static universe record is invalid")
        symbol = item.get("symbol")
        if not isinstance(symbol, str) or not isinstance(item.get("source_sha256"), str):
            raise FreeETFCrosscheckError("static universe identity is invalid")
        if (
            item["source_sha256"] not in source_hashes
            or date.fromisoformat(str(item.get("listing_date"))) > start
        ):
            raise FreeETFCrosscheckError("static universe source or listing date is invalid")
        actual[symbol] = {"issuer": str(item.get("issuer")), "exchange": str(item.get("exchange"))}
    if actual != expected:
        raise FreeETFCrosscheckError("static universe differs from frozen configuration")


def _official_events(
    value: dict[str, Any],
    expected: dict[str, dict[str, str]],
    start: date,
    end: date,
    source_hashes: set[str],
) -> set[tuple[str, str, str, str]]:
    if value.get("kind") != "v2_global_etf_issuer_actions" or value.get("coverage") != {
        "start": start.isoformat(),
        "end": end.isoformat(),
    }:
        raise FreeETFCrosscheckError("issuer action scope is invalid")
    sources = value.get("symbol_source_sha256")
    records = value.get("events")
    if (
        not isinstance(sources, dict)
        or not isinstance(records, list)
        or set(sources) != set(expected)
    ):
        raise FreeETFCrosscheckError("issuer action source coverage is invalid")
    if not all(isinstance(item, str) and item in source_hashes for item in sources.values()):
        raise FreeETFCrosscheckError("issuer action source is not captured")
    output: set[tuple[str, str, str, str]] = set()
    for item in records:
        if not isinstance(item, dict):
            raise FreeETFCrosscheckError("issuer action record is invalid")
        symbol, event_type, ex_date, value_text = (
            item.get("symbol"),
            item.get("event_type"),
            item.get("ex_date"),
            item.get("value"),
        )
        if (
            symbol not in expected
            or event_type not in {"dividend", "split"}
            or not isinstance(ex_date, str)
            or not isinstance(value_text, str)
        ):
            raise FreeETFCrosscheckError("issuer action identity is invalid")
        event_date = date.fromisoformat(ex_date)
        if event_date < start or event_date > end:
            raise FreeETFCrosscheckError("issuer action lies outside frozen window")
        output.add((symbol, event_type, ex_date, _decimal(value_text)))
    return output


def _yahoo_observations(
    root: Path, universe: dict[str, dict[str, str]], start: date, end: date
) -> tuple[set[date], set[tuple[str, str, str, str]]]:
    sessions: set[date] = set()
    events: set[tuple[str, str, str, str]] = set()
    for manifest_path in root.glob("*/manifests/*.json"):
        manifest = _pinned_object(manifest_path, "Yahoo manifest")
        symbol = manifest.get("symbol")
        if symbol not in universe:
            continue
        raw_file = manifest.get("raw_file")
        if (
            not isinstance(raw_file, dict)
            or not isinstance(raw_file.get("relative_path"), str)
            or not isinstance(raw_file.get("sha256"), str)
        ):
            raise FreeETFCrosscheckError("Yahoo raw manifest is invalid")
        raw = _regular_bytes((root / raw_file["relative_path"]).resolve(), 64 * 1024 * 1024)
        if sha256(raw).hexdigest() != raw_file["sha256"]:
            raise FreeETFCrosscheckError("Yahoo raw response SHA-256 mismatch")
        series = _yahoo_series(raw)
        timestamps = cast(list[Any], series["timestamp"])
        quote = cast(dict[str, Any], series["indicators"]["quote"][0])
        for index, timestamp in enumerate(timestamps):
            session = datetime.fromtimestamp(cast(int, timestamp), UTC).date()
            if start <= session <= end and all(
                quote[name][index] is not None for name in RAW_FIELDS
            ):
                sessions.add(session)
        raw_events = cast(dict[str, Any], series.get("events", {}))
        for event_type, key, value_key in (
            ("dividend", "dividends", "amount"),
            ("split", "splits", "numerator"),
        ):
            block = raw_events.get(key, {})
            if not isinstance(block, dict):
                continue
            for item in block.values():
                if not isinstance(item, dict):
                    raise FreeETFCrosscheckError("Yahoo event record is invalid")
                event_date = datetime.fromtimestamp(cast(int, item["date"]), UTC).date()
                if start <= event_date <= end:
                    value = _decimal(str(item[value_key]))
                    if event_type == "split":
                        value = _decimal(str(Decimal(value) / Decimal(str(item["denominator"]))))
                    events.add((cast(str, symbol), event_type, event_date.isoformat(), value))
    return sessions, events


def _yahoo_series(raw: bytes) -> dict[str, Any]:
    series = _object(raw, "Yahoo raw response").get("chart", {}).get("result", [])
    if not isinstance(series, list) or len(series) != 1 or not isinstance(series[0], dict):
        raise FreeETFCrosscheckError("Yahoo raw response schema is invalid")
    item = cast(dict[str, Any], series[0])
    if not isinstance(item.get("timestamp"), list) or not isinstance(item.get("indicators"), dict):
        raise FreeETFCrosscheckError("Yahoo raw daily series is invalid")
    quotes = item["indicators"].get("quote")
    if not isinstance(quotes, list) or len(quotes) != 1 or not isinstance(quotes[0], dict):
        raise FreeETFCrosscheckError("Yahoo raw quote series is invalid")
    if any(
        not isinstance(quotes[0].get(name), list) or len(quotes[0][name]) != len(item["timestamp"])
        for name in RAW_FIELDS
    ):
        raise FreeETFCrosscheckError("Yahoo raw quote lengths are invalid")
    return item


def _decimal(value: str) -> str:
    try:
        parsed = Decimal(value)
    except InvalidOperation as error:
        raise FreeETFCrosscheckError("event value is invalid") from error
    if not parsed.is_finite() or parsed <= 0:
        raise FreeETFCrosscheckError("event value must be positive")
    return format(parsed.normalize(), "f")
