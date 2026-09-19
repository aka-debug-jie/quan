"""Compile the current EXQ-001 evidence state without exporting market values."""

from __future__ import annotations

import argparse
import json
import stat
from hashlib import sha256
from pathlib import Path
from typing import Any

import yaml

from quant_stack_v2.dev_contract import canonical, write_blob
from quant_stack_v2.exq001 import qualify
from quant_stack_v2.exq_candidate_replay import REQUIRED_EVIDENCE


def _pinned(path: Path, digest: str) -> dict[str, Any]:
    """Load a hash-pinned regular JSON evidence object."""
    info = path.lstat()
    if not stat.S_ISREG(info.st_mode) or stat.S_ISLNK(info.st_mode):
        raise ValueError("input must be a regular non-symlink artifact")
    raw = path.read_bytes()
    if sha256(raw).hexdigest() != digest:
        raise ValueError("input SHA-256 mismatch")
    value = json.loads(raw)
    if not isinstance(value, dict):
        raise ValueError("input must be an object")
    return value


def _ledger(path: Path) -> str:
    """Validate the minimal event-boundary ledger without treating it as accounting."""
    raw = path.read_bytes()
    value = yaml.safe_load(raw)
    if not isinstance(value, dict) or value.get("ledger_id") != "EXQ-001-CORPORATE-LEDGER-V1":
        raise ValueError("corporate ledger schema is invalid")
    events = value.get("events")
    if not isinstance(events, list) or len(events) != 6:
        raise ValueError("corporate ledger event count is invalid")
    pending = sum(
        item.get("status") == "FACTOR_RECONCILIATION_PENDING"
        for item in events
        if isinstance(item, dict)
    )
    if pending != 3:
        raise ValueError("equity distribution ledger status is invalid")
    return sha256(raw).hexdigest()


def compile_current(
    development_root: Path,
    sealed_root: Path,
    repo_root: Path,
    registry: Path,
    raw_probe: Path,
    raw_probe_sha256: str,
    history: Path,
    history_sha256: str,
    corporate_ledger: Path,
) -> dict[str, Any]:
    """Compile only evidence mechanically available in the current artifacts."""
    qualification = qualify(development_root, sealed_root, repo_root, registry)
    probe = _pinned(raw_probe, raw_probe_sha256)
    history_value = _pinned(history, history_sha256)
    ledger_sha256 = _ledger(corporate_ledger)
    if probe.get("status") != "DIAGNOSTIC_ONLY_NOT_EXECUTION_QUALIFIED":
        raise ValueError("unexpected Qlib raw probe status")
    if history_value.get("status") != "HISTORY_REVALIDATION_NOT_EXECUTION_QUALIFICATION":
        raise ValueError("unexpected history revalidation status")
    lifecycle = qualification.get("lifecycle_and_suspension")
    if not isinstance(lifecycle, dict) or not isinstance(
        lifecycle.get("free_residual_intersection"), list
    ):
        raise ValueError("legacy qualification lacks exact residual intersection")
    residual = lifecycle["free_residual_intersection"]
    raw_counts = probe.get("status_counts")
    if not isinstance(raw_counts, dict):
        raise ValueError("Qlib raw probe lacks status counts")
    raw_state = "MISSING" if raw_counts.get("MISSING_OR_NONFINITE") else "EMPTY_PROVIDER_RESPONSE"
    evidence = {
        "raw_execution": raw_state,
        "corporate_actions": "FACTOR_RECONCILIATION_PENDING",
        "trading_status": "RETROSPECTIVE_ONLY",
        "price_limit": "MISSING",
        "board_lot": "MISSING",
        "t_plus_one": "MISSING",
        "liquidity": "MISSING",
        "cost_model": "MISSING",
    }
    if set(evidence) != set(REQUIRED_EVIDENCE):
        raise ValueError("compiler evidence contract drift")
    scope_membership = qualification.get("scope_membership")
    provenance = qualification.get("provenance")
    if not isinstance(scope_membership, dict) or not isinstance(provenance, dict):
        raise ValueError("legacy qualification lacks scope provenance")
    domain_key_count = scope_membership.get("symbol_count")
    code_sha256 = provenance.get("code_sha256")
    if not isinstance(domain_key_count, int) or not isinstance(code_sha256, str):
        raise ValueError("legacy qualification scope provenance is invalid")
    keys: list[dict[str, Any]] = []
    for row in residual:
        if not isinstance(row, dict):
            raise ValueError("invalid residual intersection row")
        symbol, session = row.get("symbol"), row.get("expected_session")
        if not isinstance(symbol, str) or not isinstance(session, str):
            raise ValueError("invalid residual intersection key")
        keys.append(
            {
                "symbol": symbol,
                "signal_session": session,
                "execution_session": session,
                "evidence": evidence.copy(),
            }
        )
    return {
        "schema_version": 1,
        "scope": "EXQ001_CANDIDATE_SCOPE_V1",
        "formal_pit_status": "BLOCKED_DATA",
        "formal_research_status": "BLOCKED_DATA",
        "csi500": "NOT_STARTED",
        "domain_key_count": domain_key_count,
        "domain_evidence": evidence,
        "candidate_keys": keys,
        "provenance": {
            "legacy_qualification_code_sha256": code_sha256,
            "raw_probe_sha256": raw_probe_sha256,
            "history_sha256": history_sha256,
            "corporate_ledger_sha256": ledger_sha256,
            "registry_sha256": sha256(registry.read_bytes()).hexdigest(),
        },
    }


def main() -> None:
    """Persist the current conservative compiled-scope evidence as a CAS object."""
    parser = argparse.ArgumentParser()
    parser.add_argument("--development-root", type=Path, required=True)
    parser.add_argument("--sealed-root", type=Path, required=True)
    parser.add_argument("--repo-root", type=Path, required=True)
    parser.add_argument("--registry", type=Path, required=True)
    parser.add_argument("--raw-probe", type=Path, required=True)
    parser.add_argument("--raw-probe-sha256", required=True)
    parser.add_argument("--history", type=Path, required=True)
    parser.add_argument("--history-sha256", required=True)
    parser.add_argument("--corporate-ledger", type=Path, required=True)
    parser.add_argument("--result-root", type=Path, required=True)
    args = parser.parse_args()
    result = compile_current(
        args.development_root,
        args.sealed_root,
        args.repo_root,
        args.registry,
        args.raw_probe,
        args.raw_probe_sha256,
        args.history,
        args.history_sha256,
        args.corporate_ledger,
    )
    identity = write_blob(args.result_root / "compiled_scope", canonical(result))
    print(
        json.dumps(
            {"compiled_scope_sha256": identity, "keys": len(result["candidate_keys"])},
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
