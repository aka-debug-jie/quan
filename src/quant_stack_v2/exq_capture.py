"""One-shot, scope-bound BaoStock raw-data capture for EXQ-001."""

from __future__ import annotations

import argparse
import json
import subprocess
from hashlib import sha256
from pathlib import Path
from typing import cast

from quant_stack_v2.af002 import _blob, _mapping, _string
from quant_stack_v2.af003 import DEV001_SUMMARY_SHA256
from quant_stack_v2.baostock_provider import capture_baostock_batch
from quant_stack_v2.dev_contract import canonical, write_blob
from quant_stack_v2.dev_real_staged_view import load_staged_view
from quant_stack_v2.exq001 import EXQ001Error, qualify


def capture(
    development_root: Path,
    sealed_root: Path,
    repo_root: Path,
    registry_path: Path,
    *,
    allow_network: bool,
) -> dict[str, object]:
    """Capture only the actual DEV-001 candidate raw dependency span."""
    if not allow_network:
        raise EXQ001Error("--allow-network is required for EXQ-001 raw capture")
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
    manifests, failures = capture_baostock_batch(
        sealed_root / "artifacts/v2/exq001_candidate_scope/free_raw_baostock",
        symbols=view.access.symbols,
        start_date=view.access.raw_dependency_span.start,
        end_date=view.access.raw_dependency_span.end,
        allow_network=True,
        provider_version="baostock-0.8.9",
    )
    return {
        "schema_version": 1,
        "kind": "exq001_scope_bound_raw_capture",
        "status": "CAPTURE_COMPLETE" if not failures else "CAPTURE_PARTIAL",
        "qualification_before_capture": qualification["status"],
        "scope": qualification["scope"],
        "symbols_requested": len(view.access.symbols),
        "raw_dependency_span": view.access.raw_dependency_span.model_dump(mode="json"),
        "provider": "baostock",
        "provider_evidence_level": "INDEPENDENT_PROVIDER_CONFIRMED_NOT_OFFICIAL",
        "successful_manifests": [
            {
                "symbol": item.symbol,
                "manifest_sha256": item.identity_sha256,
                "raw_sha256": item.raw_sha256,
                "row_count": item.row_count,
            }
            for item in manifests
        ],
        "failures": [item.__dict__ for item in failures],
        "unresolved_residual_intersection_count": _mapping(
            qualification, "lifecycle_and_suspension"
        )["free_residual_intersection_count"],
        "FORMAL_PIT_STATUS": "BLOCKED_DATA",
        "FORMAL_RESEARCH_STATUS": "BLOCKED_DATA",
        "CSI500": "NOT_STARTED",
        "provenance": {
            "registry_sha256": sha256(registry_path.read_bytes()).hexdigest(),
            "qualification_result_sha256": (
                "d76df75580daaebcba9ca918c9854aa255d37f5d0d88c3cfeef71f2ee39d7862"
            ),
            "contract_sha256": _string(identities, "contract_sha256"),
            "evidence_sha256": _string(identities, "evidence_sha256"),
            "view_sha256": view.manifest_sha256,
            "code_sha256": sha256(
                (repo_root / "src/quant_stack_v2/exq_capture.py").read_bytes()
            ).hexdigest(),
            "git_commit": _commit(repo_root),
        },
    }


def persist(payload: dict[str, object], root: Path) -> str:
    """Publish the capture receipt without exposing raw market rows to development."""
    return write_blob(root / "raw_capture_receipts", canonical(payload))


def render_markdown(payload: dict[str, object], identity: str) -> str:
    """Render a concise capture receipt that preserves its qualification boundary."""
    manifests = cast(list[object], payload["successful_manifests"])
    failures = cast(list[object], payload["failures"])
    return (
        "# EXQ-001 candidate-scope raw capture\n\n"
        f"Status: {payload['status']}; receipt identity: {identity}.\n\n"
        f"- requested symbols: {payload['symbols_requested']}\n"
        f"- successful provider manifests: {len(manifests)}\n"
        f"- bounded failures: {len(failures)}\n"
        "- unresolved residual intersection: "
        f"{payload['unresolved_residual_intersection_count']}\n\n"
        "BaoStock records are independent-provider raw evidence only. This receipt "
        "does not qualify corporate actions, historical execution rules, PIT, "
        "formal research, or CSI500.\n"
    )


def _commit(repo_root: Path) -> str:
    return subprocess.run(
        ["git", "-C", str(repo_root), "rev-parse", "HEAD"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()


def main() -> None:
    """Execute only when the operator explicitly enables network collection."""
    parser = argparse.ArgumentParser()
    parser.add_argument("--development-root", type=Path, required=True)
    parser.add_argument("--sealed-root", type=Path, required=True)
    parser.add_argument("--repo-root", type=Path, required=True)
    parser.add_argument("--registry", type=Path, required=True)
    parser.add_argument("--result-root", type=Path, required=True)
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--allow-network", action="store_true")
    args = parser.parse_args()
    payload = capture(
        args.development_root,
        args.sealed_root,
        args.repo_root,
        args.registry,
        allow_network=args.allow_network,
    )
    identity = persist(payload, args.result_root)
    args.report.write_text(render_markdown(payload, identity), encoding="utf-8")
    print(json.dumps({"receipt_sha256": identity, "status": payload["status"]}, sort_keys=True))


if __name__ == "__main__":
    main()
