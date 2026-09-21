"""Offline validation of sealed Tencent history evidence."""

from __future__ import annotations

import argparse
import csv
import io
import json
import stat
from datetime import date
from hashlib import sha256
from pathlib import Path
from typing import Any, cast

from quant_stack_v2.af002 import _string
from quant_stack_v2.af003 import DEV001_SUMMARY_SHA256
from quant_stack_v2.dev_contract import canonical, write_blob
from quant_stack_v2.exq_tencent_history_capture import HistoryRequest, resolve_scope
from quant_stack_v2.tencent_provider import FIELDS

MANIFEST_FIELDS = {
    "symbol",
    "start_date",
    "end_date",
    "fields",
    "provider_version",
    "raw_sha256",
    "row_count",
}


class TencentVerificationError(ValueError):
    """Raised when sealed Tencent evidence does not match the frozen scope."""


def request_scope_sha256(requests: tuple[HistoryRequest, ...]) -> str:
    """Return the canonical identity of the exact approved request scope."""
    body = {
        "requests": [
            {
                "symbol": symbol,
                "start_date": start.isoformat(),
                "end_date": end.isoformat(),
            }
            for symbol, start, end in requests
        ]
    }
    return sha256(canonical(body)).hexdigest()


def _regular_bytes(path: Path, *, maximum: int) -> bytes:
    """Read a bounded regular file without accepting symlinks."""
    try:
        info = path.lstat()
    except FileNotFoundError as error:
        raise TencentVerificationError(f"missing Tencent evidence file: {path.name}") from error
    if not stat.S_ISREG(info.st_mode) or stat.S_ISLNK(info.st_mode) or info.st_size > maximum:
        raise TencentVerificationError("Tencent evidence must be a bounded regular file")
    return path.read_bytes()


def _manifest(path: Path) -> tuple[dict[str, Any], HistoryRequest, str, int]:
    """Load one manifest and bind its directory name to its canonical identity."""
    try:
        value = json.loads(_regular_bytes(path, maximum=64 * 1024))
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise TencentVerificationError("Tencent manifest JSON is invalid") from error
    if not isinstance(value, dict) or set(value) != MANIFEST_FIELDS:
        raise TencentVerificationError("Tencent manifest schema is invalid")
    manifest = cast(dict[str, Any], value)
    try:
        symbol = manifest["symbol"]
        start_text = manifest["start_date"]
        end_text = manifest["end_date"]
        fields = manifest["fields"]
        provider_version = manifest["provider_version"]
        raw_sha256 = manifest["raw_sha256"]
        row_count = manifest["row_count"]
        if (
            not isinstance(symbol, str)
            or not symbol
            or not isinstance(start_text, str)
            or not isinstance(end_text, str)
            or not isinstance(fields, list)
            or tuple(fields) != FIELDS
            or not isinstance(provider_version, str)
            or not provider_version
            or not isinstance(raw_sha256, str)
            or len(raw_sha256) != 64
            or any(character not in "0123456789abcdef" for character in raw_sha256)
            or not isinstance(row_count, int)
            or isinstance(row_count, bool)
            or row_count < 1
        ):
            raise TencentVerificationError("Tencent manifest fields are invalid")
        request = (symbol, date.fromisoformat(start_text), date.fromisoformat(end_text))
    except (TypeError, ValueError) as error:
        if isinstance(error, TencentVerificationError):
            raise
        raise TencentVerificationError("Tencent manifest fields are invalid") from error
    identity = sha256(
        json.dumps(manifest, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    if path.parent.name != identity:
        raise TencentVerificationError("Tencent manifest identity mismatch")
    return manifest, request, raw_sha256, row_count


def _response_rows(raw: bytes, request: HistoryRequest, expected_rows: int) -> int:
    """Validate one response schema, row count, dates and unique security-date keys."""
    try:
        records = list(csv.reader(io.StringIO(raw.decode(), newline="")))
    except (UnicodeDecodeError, csv.Error) as error:
        raise TencentVerificationError("Tencent response CSV is invalid") from error
    if not records or tuple(records[0]) != FIELDS:
        raise TencentVerificationError("Tencent response fields are invalid")
    rows = records[1:]
    if len(rows) != expected_rows or not rows:
        raise TencentVerificationError("Tencent response row count is invalid")
    symbol, start, end = request
    keys: set[tuple[str, date]] = set()
    for row in rows:
        if len(row) != len(FIELDS) or any(not value for value in row):
            raise TencentVerificationError("Tencent response row fields are invalid")
        try:
            session = date.fromisoformat(row[0])
        except ValueError as error:
            raise TencentVerificationError("Tencent response date is invalid") from error
        if session < start or session > end:
            raise TencentVerificationError("Tencent response date is outside approved scope")
        key = (symbol, session)
        if key in keys:
            raise TencentVerificationError("duplicate Tencent security-date key")
        keys.add(key)
    return len(rows)


def verify(
    root: Path,
    requests: tuple[HistoryRequest, ...],
    provenance: dict[str, str],
) -> dict[str, Any]:
    """Validate every manifest and raw response in the exact frozen request scope."""
    if not requests or tuple(sorted(set(requests))) != requests:
        raise TencentVerificationError("approved Tencent request scope is invalid")
    expected = set(requests)
    found: set[HistoryRequest] = set()
    manifest_identities: list[str] = []
    verified_rows = 0
    paths = sorted((root / "tencent_finance_manifests").glob("*/manifest.json"))
    if not paths:
        raise TencentVerificationError("Tencent manifests are missing")
    for path in paths:
        _, request, raw_sha256, row_count = _manifest(path)
        if request not in expected:
            raise TencentVerificationError("Tencent manifest is outside approved scope")
        if request in found:
            raise TencentVerificationError("duplicate Tencent manifest")
        raw = _regular_bytes(
            root / "tencent_finance" / raw_sha256 / "response.csv",
            maximum=64 * 1024 * 1024,
        )
        if sha256(raw).hexdigest() != raw_sha256:
            raise TencentVerificationError("Tencent response SHA-256 mismatch")
        verified_rows += _response_rows(raw, request, row_count)
        found.add(request)
        manifest_identities.append(path.parent.name)
    if found != expected:
        raise TencentVerificationError("Tencent scope coverage is incomplete")
    required_provenance = {
        "registry_sha256",
        "dev001_summary_sha256",
        "contract_sha256",
        "evidence_sha256",
        "view_sha256",
        "access_scope_sha256",
    }
    if set(provenance) != required_provenance or not all(
        isinstance(value, str) and len(value) == 64 for value in provenance.values()
    ):
        raise TencentVerificationError("Tencent scope provenance is invalid")
    return {
        "schema_version": 1,
        "kind": "exq001_tencent_history_raw_verification",
        "scope": "FROZEN_DEV001_ACCESS_SCOPE_ONLY",
        "status": "VALID",
        "raw_execution": "VALID",
        "provider": "tencent_finance_via_akshare",
        "provider_evidence_level": "INDEPENDENT_PROVIDER_CONFIRMED_NOT_OFFICIAL",
        "request_count": len(requests),
        "verified_manifest_count": len(found),
        "verified_response_count": len(found),
        "verified_rows": verified_rows,
        "request_scope_sha256": request_scope_sha256(requests),
        "manifest_set_sha256": sha256(canonical(sorted(manifest_identities))).hexdigest(),
        "FORMAL_PIT_STATUS": "BLOCKED_DATA",
        "FORMAL_RESEARCH_STATUS": "BLOCKED_DATA",
        "CSI500": "NOT_STARTED",
        "provenance": dict(sorted(provenance.items())),
    }


def main() -> None:
    """Validate the sealed scope and publish only one aggregate CAS receipt."""
    parser = argparse.ArgumentParser()
    parser.add_argument("--development-root", type=Path, required=True)
    parser.add_argument("--sealed-root", type=Path, required=True)
    parser.add_argument("--repo-root", type=Path, required=True)
    parser.add_argument("--registry", type=Path, required=True)
    parser.add_argument("--result-root", type=Path, required=True)
    args = parser.parse_args()
    _, identities, view, requests = resolve_scope(
        args.development_root,
        args.sealed_root,
        args.repo_root,
        args.registry,
    )
    provenance = {
        "registry_sha256": sha256(args.registry.read_bytes()).hexdigest(),
        "dev001_summary_sha256": DEV001_SUMMARY_SHA256,
        "contract_sha256": _string(identities, "contract_sha256"),
        "evidence_sha256": _string(identities, "evidence_sha256"),
        "view_sha256": view.manifest_sha256,
        "access_scope_sha256": view.manifest.access_scope_sha256,
    }
    result = verify(
        args.sealed_root / "artifacts/v2/exq001_candidate_scope/tencent_history_raw",
        requests,
        provenance,
    )
    identity = write_blob(args.result_root / "tencent_raw_verification", canonical(result))
    print(json.dumps({"verification_sha256": identity, "status": result["status"]}, sort_keys=True))


if __name__ == "__main__":
    main()
