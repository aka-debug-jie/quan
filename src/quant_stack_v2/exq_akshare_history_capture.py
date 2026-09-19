"""Bounded historical raw capture for the frozen EXQ-001 candidate domain."""

from __future__ import annotations

import argparse
import json
from datetime import date
from hashlib import sha256
from pathlib import Path
from typing import Any

from quant_stack_v2.af002 import _blob, _mapping, _string
from quant_stack_v2.af003 import DEV001_SUMMARY_SHA256
from quant_stack_v2.akshare_provider import capture_history_batch
from quant_stack_v2.dev_contract import canonical, write_blob
from quant_stack_v2.dev_real_staged_view import load_staged_view
from quant_stack_v2.exq001 import EXQ001Error, qualify


def scope_requests(
    symbols: tuple[str, ...], start: date, end: date
) -> tuple[tuple[str, date, date], ...]:
    """Return exactly one approved history span for every frozen access-scope symbol."""
    if not symbols or tuple(sorted(set(symbols))) != symbols or start > end:
        raise EXQ001Error("EXQ history capture scope is invalid")
    return tuple((symbol, start, end) for symbol in symbols)


def capture(
    development_root: Path,
    sealed_root: Path,
    repo_root: Path,
    registry_path: Path,
    *,
    allow_network: bool,
    workers: int,
) -> dict[str, Any]:
    """Archive only raw bars authorized by the frozen DEV-001 access manifest."""
    if not allow_network:
        raise EXQ001Error("--allow-network is required for EXQ history capture")
    qualification = qualify(development_root, sealed_root, repo_root, registry_path)
    summary = _blob(development_root / "dev001" / "summaries", DEV001_SUMMARY_SHA256)
    identities = _mapping(summary, "identities")
    view = load_staged_view(
        development_root / "dev001" / "authority",
        development_root / "dev001" / "views",
        _string(identities, "contract_sha256"),
        _string(identities, "evidence_sha256"),
        _string(identities, "view_pin_sha256"),
    )
    span = view.access.raw_dependency_span
    requests = scope_requests(view.access.symbols, span.start, span.end)
    manifests, failures = capture_history_batch(
        sealed_root / "artifacts/v2/exq001_candidate_scope/akshare_history_raw",
        requests=requests,
        allow_network=True,
        provider_version="akshare-installed",
        workers=workers,
    )
    return {
        "schema_version": 1,
        "kind": "exq001_akshare_history_raw_capture",
        "scope": "FROZEN_DEV001_ACCESS_SCOPE_ONLY",
        "status": "CAPTURE_COMPLETE" if not failures else "CAPTURE_PARTIAL",
        "provider_evidence_level": "INDEPENDENT_PROVIDER_CONFIRMED_NOT_OFFICIAL",
        "request_count": len(requests),
        "symbol_count": len(view.access.symbols),
        "raw_dependency_span": span.model_dump(mode="json"),
        "required_fields": ["open", "high", "low", "close", "volume", "amount"],
        "successful_manifests": len(manifests),
        "empty_history_responses": sum(item.row_count == 0 for item in manifests),
        "captured_row_count": sum(item.row_count for item in manifests),
        "failures": [item.__dict__ for item in failures],
        "qualification_before_capture": qualification["status"],
        "FORMAL_PIT_STATUS": "BLOCKED_DATA",
        "FORMAL_RESEARCH_STATUS": "BLOCKED_DATA",
        "CSI500": "NOT_STARTED",
        "provenance": {
            "registry_sha256": sha256(registry_path.read_bytes()).hexdigest(),
            "dev001_summary_sha256": DEV001_SUMMARY_SHA256,
            "contract_sha256": _string(identities, "contract_sha256"),
            "evidence_sha256": _string(identities, "evidence_sha256"),
            "view_sha256": view.manifest_sha256,
            "access_scope_sha256": view.manifest.access_scope_sha256,
            "code_sha256": sha256(
                (repo_root / "src/quant_stack_v2/exq_akshare_history_capture.py").read_bytes()
            ).hexdigest(),
        },
    }


def main() -> None:
    """Capture the frozen candidate domain only after explicit network authorization."""
    parser = argparse.ArgumentParser()
    parser.add_argument("--development-root", type=Path, required=True)
    parser.add_argument("--sealed-root", type=Path, required=True)
    parser.add_argument("--repo-root", type=Path, required=True)
    parser.add_argument("--registry", type=Path, required=True)
    parser.add_argument("--result-root", type=Path, required=True)
    parser.add_argument("--allow-network", action="store_true")
    parser.add_argument("--workers", type=int, default=4)
    args = parser.parse_args()
    payload = capture(
        args.development_root,
        args.sealed_root,
        args.repo_root,
        args.registry,
        allow_network=args.allow_network,
        workers=args.workers,
    )
    identity = write_blob(args.result_root / "akshare_history_raw_capture", canonical(payload))
    print(json.dumps({"receipt_sha256": identity, "status": payload["status"]}, sort_keys=True))


if __name__ == "__main__":
    main()
