"""Exact official-evidence queue for EXQ-001 residual keys."""

from __future__ import annotations

import argparse
import json
from collections import defaultdict
from hashlib import sha256
from pathlib import Path
from typing import cast

import yaml

from quant_stack_v2.af002 import _mapping
from quant_stack_v2.dev_contract import canonical, write_blob
from quant_stack_v2.exq001 import EXQ001Error, qualify


def build_queue(qualification: dict[str, object], rule_contract_path: Path) -> dict[str, object]:
    """Group only exact candidate residual keys into exchange-specific official tasks."""
    rules = yaml.safe_load(rule_contract_path.read_text(encoding="utf-8"))
    if (
        not isinstance(rules, dict)
        or rules.get("status") != "PREREGISTERED_OFFICIAL_EVIDENCE_REQUIRED"
    ):
        raise EXQ001Error("EXQ official rule contract is invalid")
    rows = _mapping(qualification, "lifecycle_and_suspension").get("free_residual_intersection")
    if not isinstance(rows, list):
        raise EXQ001Error("EXQ residual intersection is unavailable")
    grouped: dict[str, list[str]] = defaultdict(list)
    for row in cast(list[dict[str, object]], rows):
        symbol, session = row.get("symbol"), row.get("expected_session")
        if not isinstance(symbol, str) or not isinstance(session, str):
            raise EXQ001Error("EXQ residual key is invalid")
        grouped[symbol].append(session)
    tasks = [
        {
            "symbol": symbol,
            "exchange": "SSE" if symbol.startswith("sh") else "SZSE",
            "exact_sessions": sorted(set(sessions)),
            "official_suspension_source": "SSE_STOP_RESUME_QUERY"
            if symbol.startswith("sh")
            else "SZSE_MONTHLY_THEN_ISSUER_NOTICE",
            "corporate_action_source": "EXCHANGE_OR_CNINFO_ISSUER_NOTICE",
            "st_status_source": "EXCHANGE_OR_CNINFO_ISSUER_NOTICE",
        }
        for symbol, sessions in sorted(grouped.items())
    ]
    if sum(len(task["exact_sessions"]) for task in tasks) != len(rows):
        raise EXQ001Error("official queue conservation failure")
    return {
        "schema_version": 1,
        "kind": "exq001_candidate_scope_official_evidence_queue",
        "scope": "EXACT_FROZEN_RESIDUAL_KEYS_ONLY",
        "status": "PENDING_OFFICIAL_CAPTURE",
        "task_count": len(tasks),
        "session_count": len(rows),
        "tasks": tasks,
        "rule_contract_sha256": sha256(rule_contract_path.read_bytes()).hexdigest(),
        "formal_pit_status": "BLOCKED_DATA",
        "formal_research_status": "BLOCKED_DATA",
        "csi500": "NOT_STARTED",
    }


def main() -> None:
    """Write one content-addressed queue from the sealed EXQ identity chain."""
    parser = argparse.ArgumentParser()
    parser.add_argument("--development-root", type=Path, required=True)
    parser.add_argument("--sealed-root", type=Path, required=True)
    parser.add_argument("--repo-root", type=Path, required=True)
    parser.add_argument("--registry", type=Path, required=True)
    parser.add_argument("--rule-contract", type=Path, required=True)
    parser.add_argument("--result-root", type=Path, required=True)
    args = parser.parse_args()
    qualification = qualify(args.development_root, args.sealed_root, args.repo_root, args.registry)
    queue = build_queue(qualification, args.rule_contract)
    identity = write_blob(args.result_root / "official_evidence_queue", canonical(queue))
    print(
        json.dumps(
            {
                "queue_sha256": identity,
                "tasks": queue["task_count"],
                "sessions": queue["session_count"],
            },
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
