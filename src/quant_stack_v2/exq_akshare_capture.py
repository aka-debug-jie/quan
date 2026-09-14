"""Scope-bound independent raw capture for EXQ-001."""

from __future__ import annotations

import argparse
import json
from datetime import date
from hashlib import sha256
from pathlib import Path
from typing import cast

from quant_stack_v2.af002 import _mapping
from quant_stack_v2.akshare_provider import capture_batch
from quant_stack_v2.dev_contract import canonical, write_blob
from quant_stack_v2.exq001 import EXQ001Error, qualify


def capture(
    development_root: Path, sealed_root: Path, repo_root: Path, registry_path: Path
) -> dict[str, object]:
    """Capture independent raw evidence only for frozen EXQ residual keys."""
    qualification = qualify(development_root, sealed_root, repo_root, registry_path)
    rows = _mapping(qualification, "lifecycle_and_suspension").get("free_residual_intersection")
    if not isinstance(rows, list):
        raise EXQ001Error("EXQ residual intersection is unavailable")
    requests = tuple(
        sorted(
            (
                str(row["symbol"]),
                date.fromisoformat(str(row["expected_session"])),
            )
            for row in cast(list[dict[str, object]], rows)
        )
    )
    manifests, failures = capture_batch(
        sealed_root / "artifacts/v2/exq001_candidate_scope/akshare_raw",
        requests=requests,
        allow_network=True,
        provider_version="akshare-installed",
        workers=4,
    )
    return {
        "schema_version": 1,
        "kind": "exq001_akshare_independent_raw_capture",
        "status": "CAPTURE_COMPLETE" if not failures else "CAPTURE_PARTIAL",
        "scope": "EXACT_FROZEN_RESIDUAL_KEYS_ONLY",
        "provider_evidence_level": "INDEPENDENT_PROVIDER_CONFIRMED_NOT_OFFICIAL",
        "requests": len(requests),
        "successful_manifests": len(manifests),
        "empty_provider_rows": sum(item.row_count == 0 for item in manifests),
        "failures": [item.__dict__ for item in failures],
        "formal_pit_status": "BLOCKED_DATA",
        "formal_research_status": "BLOCKED_DATA",
        "csi500": "NOT_STARTED",
        "provenance": {
            "registry_sha256": sha256(registry_path.read_bytes()).hexdigest(),
            "code_sha256": sha256(
                (repo_root / "src/quant_stack_v2/exq_akshare_capture.py").read_bytes()
            ).hexdigest(),
        },
    }


def main() -> None:
    """Run only under the operator-approved network capture script."""
    parser = argparse.ArgumentParser()
    parser.add_argument("--development-root", type=Path, required=True)
    parser.add_argument("--sealed-root", type=Path, required=True)
    parser.add_argument("--repo-root", type=Path, required=True)
    parser.add_argument("--registry", type=Path, required=True)
    parser.add_argument("--result-root", type=Path, required=True)
    args = parser.parse_args()
    payload = capture(args.development_root, args.sealed_root, args.repo_root, args.registry)
    identity = write_blob(args.result_root / "akshare_raw_capture", canonical(payload))
    print(json.dumps({"receipt_sha256": identity, "status": payload["status"]}, sort_keys=True))


if __name__ == "__main__":
    main()
