"""Offline, non-promoting audit of the archived global-ETF Yahoo responses."""

from __future__ import annotations

import json
import stat
from datetime import UTC, datetime
from hashlib import sha256
from pathlib import Path
from typing import Any, cast

from quant_stack_v2.dev_contract import canonical, write_blob
from quant_stack_v2.yahoo_etf import DEFAULT_YAHOO_ETF_SYMBOLS, RESEARCH_ADJUSTED_ONLY

RAW_FIELDS = ("open", "high", "low", "close", "volume")
AUDIT_STATUS = "FREE_RESEARCH_ARCHIVE_VALIDATED_NOT_EXECUTION_QUALIFIED"


class FreeETFAuditError(ValueError):
    """Raised when an archived Yahoo response cannot support the free audit."""


def audit_archive(
    report_path: Path,
    expected_report_sha256: str,
    expected_symbols: tuple[str, ...] = DEFAULT_YAHOO_ETF_SYMBOLS,
) -> dict[str, Any]:
    """Verify frozen raw-response coverage without exposing prices or promoting its use."""
    report_bytes = _regular_bytes(report_path, 4 * 1024 * 1024)
    if sha256(report_bytes).hexdigest() != expected_report_sha256:
        raise FreeETFAuditError("Yahoo report SHA-256 mismatch")
    report = _object(report_bytes, "Yahoo report")
    manifests = report.get("manifests")
    if report.get("usage_level") != RESEARCH_ADJUSTED_ONLY or not isinstance(manifests, list):
        raise FreeETFAuditError("Yahoo report is not the frozen research archive")
    manifest_ids = tuple(manifests)
    if not all(isinstance(item, str) and len(item) == 64 for item in manifest_ids):
        raise FreeETFAuditError("Yahoo report manifest identities are invalid")
    if len(set(manifest_ids)) != len(manifest_ids):
        raise FreeETFAuditError("Yahoo report contains duplicate manifest identities")
    root = report_path.parent.parent
    summaries = [_audit_manifest(root, identity) for identity in manifest_ids]
    symbols = tuple(item["symbol"] for item in summaries)
    if set(symbols) != set(expected_symbols) or len(symbols) != len(expected_symbols):
        raise FreeETFAuditError("Yahoo archive symbols differ from the frozen ETF universe")
    return {
        "schema_version": 1,
        "kind": "v2_global_etf_usd_free_research_audit",
        "status": AUDIT_STATUS,
        "dataset_id": "yahoo_global_etf_research_v1",
        "usage_level": RESEARCH_ADJUSTED_ONLY,
        "report_sha256": expected_report_sha256,
        "symbol_count": len(summaries),
        "symbols": sorted(summaries, key=lambda item: str(item["symbol"])),
        "issuer_action_crosscheck": "NOT_PROVIDED",
        "official_calendar_crosscheck": "NOT_PROVIDED",
        "FORMAL_PIT_STATUS": "BLOCKED_DATA",
        "FORMAL_RESEARCH_STATUS": "BLOCKED_DATA",
        "CSI500": "NOT_STARTED",
        "forbidden_uses": ["execution", "backtest", "paper_broker", "promotion"],
    }


def persist_audit(result: dict[str, Any], artifact_root: Path) -> str:
    """Publish the audit summary as a content-addressed JSON receipt."""
    return write_blob(artifact_root / "free_research_audit", canonical(result))


def _audit_manifest(root: Path, identity: str) -> dict[str, Any]:
    candidates = tuple(root.glob(f"*/manifests/{identity}.json"))
    if len(candidates) != 1:
        raise FreeETFAuditError("Yahoo manifest is missing or ambiguous")
    manifest = _object(_regular_bytes(candidates[0], 256 * 1024), "Yahoo manifest")
    if manifest.get("manifest_id") != identity:
        raise FreeETFAuditError("Yahoo manifest identity differs from report")
    symbol = manifest.get("symbol")
    raw_file = manifest.get("raw_file")
    raw_sha256 = manifest.get("raw_sha256")
    if not isinstance(symbol, str) or not symbol or not isinstance(raw_file, dict):
        raise FreeETFAuditError("Yahoo manifest schema is invalid")
    relative_path = raw_file.get("relative_path")
    file_sha256 = raw_file.get("sha256")
    if (
        not isinstance(relative_path, str)
        or not isinstance(file_sha256, str)
        or not isinstance(raw_sha256, str)
        or file_sha256 != raw_sha256
        or len(raw_sha256) != 64
    ):
        raise FreeETFAuditError("Yahoo raw manifest binding is invalid")
    raw_path = (root / relative_path).resolve()
    if not raw_path.is_relative_to(root.resolve()):
        raise FreeETFAuditError("Yahoo raw path escapes archive root")
    raw = _regular_bytes(raw_path, 64 * 1024 * 1024)
    if sha256(raw).hexdigest() != raw_sha256:
        raise FreeETFAuditError("Yahoo raw response SHA-256 mismatch")
    sessions, complete_sessions, event_count, first_session, last_session = _summarize_raw(raw)
    return {
        "symbol": symbol,
        "raw_sha256": raw_sha256,
        "raw_sessions": sessions,
        "complete_raw_ohlcv_sessions": complete_sessions,
        "raw_event_observations": event_count,
        "first_session": first_session,
        "last_session": last_session,
    }


def _summarize_raw(raw: bytes) -> tuple[int, int, int, str, str]:
    series = _series(_object(raw, "Yahoo raw response"))
    timestamps = series.get("timestamp")
    indicators = series.get("indicators")
    if not isinstance(timestamps, list) or not isinstance(indicators, dict):
        raise FreeETFAuditError("Yahoo raw response lacks daily series")
    quotes = indicators.get("quote")
    if not isinstance(quotes, list) or len(quotes) != 1 or not isinstance(quotes[0], dict):
        raise FreeETFAuditError("Yahoo raw response lacks raw OHLCV fields")
    fields = cast(dict[str, Any], quotes[0])
    if any(
        not isinstance(fields.get(name), list) or len(fields[name]) != len(timestamps)
        for name in RAW_FIELDS
    ):
        raise FreeETFAuditError("Yahoo raw OHLCV lengths differ from timestamps")
    dates = [_session_date(item) for item in timestamps]
    if len(set(dates)) != len(dates):
        raise FreeETFAuditError("Yahoo raw response has duplicate sessions")
    complete = sum(
        all(fields[name][index] is not None for name in RAW_FIELDS) for index in range(len(dates))
    )
    events = series.get("events", {})
    if not isinstance(events, dict):
        raise FreeETFAuditError("Yahoo raw events schema is invalid")
    event_count = sum(len(value) for value in events.values() if isinstance(value, dict))
    if not dates or complete == 0:
        raise FreeETFAuditError("Yahoo raw response has no complete OHLCV sessions")
    return len(dates), complete, event_count, min(dates), max(dates)


def _series(raw: dict[str, Any]) -> dict[str, Any]:
    chart = raw.get("chart")
    if not isinstance(chart, dict) or not isinstance(chart.get("result"), list):
        raise FreeETFAuditError("Yahoo raw response chart schema is invalid")
    results = chart["result"]
    if len(results) != 1 or not isinstance(results[0], dict):
        raise FreeETFAuditError("Yahoo raw response must contain one chart series")
    return cast(dict[str, Any], results[0])


def _session_date(value: object) -> str:
    if not isinstance(value, int) or isinstance(value, bool):
        raise FreeETFAuditError("Yahoo raw timestamp is invalid")
    return datetime.fromtimestamp(value, UTC).date().isoformat()


def _regular_bytes(path: Path, maximum: int) -> bytes:
    try:
        info = path.lstat()
    except FileNotFoundError as error:
        raise FreeETFAuditError("Yahoo archive artifact is missing") from error
    if not stat.S_ISREG(info.st_mode) or stat.S_ISLNK(info.st_mode) or info.st_size > maximum:
        raise FreeETFAuditError("Yahoo archive artifact is not a bounded regular file")
    return path.read_bytes()


def _object(raw: bytes, name: str) -> dict[str, Any]:
    try:
        value = json.loads(raw)
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise FreeETFAuditError(f"{name} is not valid JSON") from error
    if not isinstance(value, dict):
        raise FreeETFAuditError(f"{name} is not a JSON object")
    return cast(dict[str, Any], value)
