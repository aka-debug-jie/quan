"""Offline tests for the non-promoting global-ETF free research audit."""

import json
from datetime import UTC, datetime
from hashlib import sha256
from pathlib import Path
from typing import Any

import pytest

from quant_stack_v2.dev_contract import canonical
from quant_stack_v2.free_etf_audit import AUDIT_STATUS, FreeETFAuditError, audit_archive
from quant_stack_v2.yahoo_etf import RESEARCH_ADJUSTED_ONLY


def _raw(*, duplicate_session: bool = False, omit_field: str | None = None) -> bytes:
    timestamps = [
        int(datetime(2020, 1, 2, tzinfo=UTC).timestamp()),
        int(datetime(2020, 1, 3, tzinfo=UTC).timestamp()),
    ]
    if duplicate_session:
        timestamps[1] = timestamps[0]
    quote: dict[str, list[int]] = {
        "open": [1, 2],
        "high": [2, 3],
        "low": [1, 2],
        "close": [2, 3],
        "volume": [10, 20],
    }
    if omit_field is not None:
        del quote[omit_field]
    payload = {
        "chart": {
            "result": [
                {
                    "timestamp": timestamps,
                    "indicators": {"quote": [quote]},
                    "events": {"dividends": {}},
                }
            ]
        }
    }
    return json.dumps(payload).encode()


def _add_symbol(root: Path, symbol: str, raw: bytes) -> str:
    raw_sha256 = sha256(raw).hexdigest()
    snapshot = root / raw_sha256
    raw_path = snapshot / "raw" / "response.json"
    raw_path.parent.mkdir(parents=True, exist_ok=True)
    raw_path.write_bytes(raw)
    manifest: dict[str, Any] = {
        "symbol": symbol,
        "manifest_id": "",
        "raw_sha256": raw_sha256,
        "raw_file": {"relative_path": str(raw_path.relative_to(root)), "sha256": raw_sha256},
    }
    identity = sha256(json.dumps(manifest, sort_keys=True).encode()).hexdigest()
    manifest["manifest_id"] = identity
    identity = sha256(json.dumps(manifest, sort_keys=True).encode()).hexdigest()
    manifest["manifest_id"] = identity
    path = snapshot / "manifests" / f"{identity}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(manifest))
    return identity


def _archive(tmp_path: Path, *, raw: bytes | None = None) -> tuple[Path, Path]:
    root = tmp_path / "data" / "external" / "yahoo_global_etf_research_v1"
    first = _add_symbol(root, "AAA", raw or _raw())
    second = _add_symbol(root, "BBB", _raw())
    report = {"usage_level": RESEARCH_ADJUSTED_ONLY, "manifests": [first, second]}
    report_path = root / "reports" / ("a" * 64 + ".json")
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_bytes(json.dumps(report).encode())
    return root, report_path


def test_free_audit_reports_raw_coverage_without_prices(tmp_path: Path) -> None:
    _, report_path = _archive(tmp_path)
    digest = sha256(report_path.read_bytes()).hexdigest()
    first = audit_archive(report_path, digest, ("AAA", "BBB"))
    second = audit_archive(report_path, digest, ("AAA", "BBB"))
    assert canonical(first) == canonical(second)
    assert first["status"] == AUDIT_STATUS
    assert first["symbols"][0]["complete_raw_ohlcv_sessions"] == 2
    assert "open" not in canonical(first).decode()


@pytest.mark.parametrize(
    ("raw", "message"),
    [
        (_raw(duplicate_session=True), "duplicate sessions"),
        (_raw(omit_field="volume"), "OHLCV lengths"),
    ],
)
def test_free_audit_rejects_invalid_raw_series(tmp_path: Path, raw: bytes, message: str) -> None:
    _, report_path = _archive(tmp_path, raw=raw)
    with pytest.raises(FreeETFAuditError, match=message):
        audit_archive(report_path, sha256(report_path.read_bytes()).hexdigest(), ("AAA", "BBB"))


def test_free_audit_rejects_tampered_raw_response(tmp_path: Path) -> None:
    root, report_path = _archive(tmp_path)
    raw_path = next(root.glob("*/raw/response.json"))
    raw_path.write_text("{}")
    with pytest.raises(FreeETFAuditError, match="SHA-256"):
        audit_archive(report_path, sha256(report_path.read_bytes()).hexdigest(), ("AAA", "BBB"))


def test_free_audit_rejects_report_or_universe_drift(tmp_path: Path) -> None:
    _, report_path = _archive(tmp_path)
    with pytest.raises(FreeETFAuditError, match="report SHA-256"):
        audit_archive(report_path, "0" * 64, ("AAA", "BBB"))
    with pytest.raises(FreeETFAuditError, match="symbols"):
        audit_archive(report_path, sha256(report_path.read_bytes()).hexdigest(), ("AAA",))
