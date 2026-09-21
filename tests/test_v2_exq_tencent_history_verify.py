"""Offline validation tests for the scoped Tencent history receipt."""

import json
from datetime import date
from hashlib import sha256
from pathlib import Path
from typing import Any

import pytest

from quant_stack_v2.dev_contract import canonical
from quant_stack_v2.exq_current_evidence_compile import _validated_tencent_state
from quant_stack_v2.exq_tencent_history_capture import HistoryRequest
from quant_stack_v2.exq_tencent_history_verify import TencentVerificationError, verify
from quant_stack_v2.tencent_provider import FIELDS


def _provenance() -> dict[str, str]:
    return {
        "registry_sha256": "a" * 64,
        "dev001_summary_sha256": "b" * 64,
        "contract_sha256": "c" * 64,
        "evidence_sha256": "d" * 64,
        "view_sha256": "e" * 64,
        "access_scope_sha256": "f" * 64,
    }


def _request(symbol: str = "sz000001") -> HistoryRequest:
    return symbol, date(2020, 1, 2), date(2020, 1, 3)


def _write_evidence(
    root: Path,
    request: HistoryRequest,
    *,
    sessions: tuple[str, ...] = ("2020-01-02", "2020-01-03"),
    fields: tuple[str, ...] = FIELDS,
    provider_version: str = "test",
    declared_raw_sha256: str | None = None,
    declared_row_count: int | None = None,
) -> None:
    symbol, start, end = request
    header = ",".join(FIELDS)
    rows = [f"{session},1,2,3,1,4,5" for session in sessions]
    raw = ("\n".join([header, *rows]) + "\n").encode()
    actual_sha256 = sha256(raw).hexdigest()
    raw_sha256 = declared_raw_sha256 or actual_sha256
    response = root / "tencent_finance" / raw_sha256 / "response.csv"
    response.parent.mkdir(parents=True, exist_ok=True)
    response.write_bytes(raw)
    manifest: dict[str, Any] = {
        "symbol": symbol,
        "start_date": start.isoformat(),
        "end_date": end.isoformat(),
        "fields": list(fields),
        "provider_version": provider_version,
        "raw_sha256": raw_sha256,
        "row_count": len(sessions) if declared_row_count is None else declared_row_count,
    }
    identity = sha256(
        json.dumps(manifest, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    path = root / "tencent_finance_manifests" / identity / "manifest.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(manifest))


def test_complete_scope_produces_deterministic_aggregate_receipt(tmp_path: Path) -> None:
    requests = (_request("sz000001"), _request("sz000002"))
    for request in requests:
        _write_evidence(tmp_path, request)
    first = verify(tmp_path, requests, _provenance())
    second = verify(tmp_path, requests, _provenance())
    assert canonical(first) == canonical(second)
    assert first["request_count"] == 2
    assert first["verified_rows"] == 4
    assert first["raw_execution"] == "VALID"


@pytest.mark.parametrize(
    ("sessions", "fields", "declared_sha", "message"),
    [
        (("2020-01-02",), ("date",), None, "fields"),
        (("2020-01-04",), FIELDS, None, "outside approved scope"),
        ((), FIELDS, None, "manifest fields"),
        (("2020-01-02",), FIELDS, "0" * 64, "SHA-256"),
        (("2020-01-02", "2020-01-02"), FIELDS, None, "duplicate"),
    ],
)
def test_invalid_manifest_or_response_is_rejected(
    tmp_path: Path,
    sessions: tuple[str, ...],
    fields: tuple[str, ...],
    declared_sha: str | None,
    message: str,
) -> None:
    request = _request()
    _write_evidence(
        tmp_path,
        request,
        sessions=sessions,
        fields=fields,
        declared_raw_sha256=declared_sha,
    )
    with pytest.raises(TencentVerificationError, match=message):
        verify(tmp_path, (request,), _provenance())


def test_missing_and_duplicate_scope_manifests_are_rejected(tmp_path: Path) -> None:
    first = _request("sz000001")
    second = _request("sz000002")
    _write_evidence(tmp_path, first)
    with pytest.raises(TencentVerificationError, match="coverage"):
        verify(tmp_path, (first, second), _provenance())
    _write_evidence(tmp_path, first, provider_version="conflict")
    with pytest.raises(TencentVerificationError, match="duplicate"):
        verify(tmp_path, (first,), _provenance())


def test_manifest_row_count_must_match_response(tmp_path: Path) -> None:
    request = _request()
    _write_evidence(tmp_path, request, declared_row_count=3)
    with pytest.raises(TencentVerificationError, match="row count"):
        verify(tmp_path, (request,), _provenance())


def test_out_of_scope_manifest_is_rejected(tmp_path: Path) -> None:
    approved = _request("sz000001")
    _write_evidence(tmp_path, approved)
    _write_evidence(tmp_path, _request("sz000002"))
    with pytest.raises(TencentVerificationError, match="outside approved scope"):
        verify(tmp_path, (approved,), _provenance())


def test_compiler_rejects_forged_or_cross_scope_valid_receipt(tmp_path: Path) -> None:
    request = _request()
    _write_evidence(tmp_path, request)
    receipt = verify(tmp_path, (request,), _provenance())
    assert _validated_tencent_state(receipt, (request,), _provenance()) == "VALID"
    forged = receipt.copy()
    forged["verified_rows"] = 0
    with pytest.raises(ValueError, match="frozen EXQ scope"):
        _validated_tencent_state(forged, (request,), _provenance())
    cross_scope = _provenance()
    cross_scope["view_sha256"] = "1" * 64
    with pytest.raises(ValueError, match="frozen EXQ scope"):
        _validated_tencent_state(receipt, (request,), cross_scope)
