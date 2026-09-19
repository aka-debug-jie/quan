"""Deterministic, fail-closed EXQ-001 candidate-scope qualification replay."""

from __future__ import annotations

import argparse
import json
import stat
from collections import Counter
from hashlib import sha256
from pathlib import Path
from typing import Any, Literal, cast

from quant_stack_v2.dev_contract import canonical, write_blob

EvidenceState = Literal[
    "VALID",
    "MISSING",
    "EMPTY_PROVIDER_RESPONSE",
    "RETROSPECTIVE_ONLY",
    "FACTOR_RECONCILIATION_PENDING",
    "NOT_APPLICABLE",
]
QualificationStatus = Literal[
    "QUALIFIED_FOR_PORTFOLIO_RESEARCH", "QUALIFIED_WITH_EXCLUSIONS", "BLOCKED_DATA"
]

REQUIRED_EVIDENCE = (
    "raw_execution",
    "corporate_actions",
    "trading_status",
    "price_limit",
    "board_lot",
    "t_plus_one",
    "liquidity",
    "cost_model",
)
VALID: EvidenceState = "VALID"


class EXQCandidateReplayError(ValueError):
    """Raised when a candidate-scope replay input is malformed or unpinned."""


def _read_pinned_json(path: Path, expected_sha256: str) -> dict[str, Any]:
    """Read one regular JSON artifact and verify its supplied content identity."""
    info = path.lstat()
    if not stat.S_ISREG(info.st_mode) or stat.S_ISLNK(info.st_mode):
        raise EXQCandidateReplayError("evidence must be a regular non-symlink file")
    raw = path.read_bytes()
    if sha256(raw).hexdigest() != expected_sha256:
        raise EXQCandidateReplayError("evidence SHA-256 mismatch")
    value = json.loads(raw)
    if not isinstance(value, dict):
        raise EXQCandidateReplayError("evidence must be a JSON object")
    return value


def _mapping(value: object, name: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise EXQCandidateReplayError(f"expected mapping: {name}")
    return cast(dict[str, Any], value)


def _records(value: object, name: str) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        raise EXQCandidateReplayError(f"expected list: {name}")
    if not all(isinstance(row, dict) for row in value):
        raise EXQCandidateReplayError(f"invalid record in: {name}")
    return cast(list[dict[str, Any]], value)


def _key(row: dict[str, Any]) -> tuple[str, str, str]:
    values = tuple(row.get(name) for name in ("symbol", "signal_session", "execution_session"))
    if not all(isinstance(value, str) and value for value in values):
        raise EXQCandidateReplayError("candidate key is incomplete")
    return cast(tuple[str, str, str], values)


def _state(value: object, name: str) -> EvidenceState:
    allowed: set[str] = {
        "VALID",
        "MISSING",
        "EMPTY_PROVIDER_RESPONSE",
        "RETROSPECTIVE_ONLY",
        "FACTOR_RECONCILIATION_PENDING",
        "NOT_APPLICABLE",
    }
    if value not in allowed:
        raise EXQCandidateReplayError(f"invalid evidence state for {name}")
    return cast(EvidenceState, value)


def _derive_row(row: dict[str, Any]) -> dict[str, Any]:
    """Derive one row without allowing a caller to self-declare qualification."""
    key = _key(row)
    evidence = _mapping(row.get("evidence"), "evidence")
    if set(evidence) != set(REQUIRED_EVIDENCE):
        raise EXQCandidateReplayError("candidate evidence keys differ from required contract")
    states = {name: _state(evidence[name], name) for name in REQUIRED_EVIDENCE}
    exclusion = _mapping(row.get("t_known_exclusion", {}), "t_known_exclusion")
    t_known = exclusion.get("status") == "OFFICIAL_T_KNOWN_UNTRADABLE"
    published = exclusion.get("published_on")
    if t_known and (not isinstance(published, str) or published > key[1]):
        raise EXQCandidateReplayError("future or missing publication cannot exclude a signal")
    missing = [name for name, state in states.items() if state != VALID]
    disposition = "QUALIFIED" if not missing else "BLOCKED"
    if missing and t_known and set(missing) <= {"trading_status", "t_plus_one"}:
        disposition = "EXCLUDED_T_KNOWN"
    return {
        "symbol": key[0],
        "signal_session": key[1],
        "execution_session": key[2],
        "evidence": states,
        "disposition": disposition,
        "blocking_evidence": missing,
        "t_known_exclusion": exclusion if t_known else None,
    }


def replay(payload: dict[str, Any], input_identities: dict[str, str]) -> dict[str, Any]:
    """Produce a canonical candidate matrix and a status derived from its rows."""
    if payload.get("schema_version") != 1 or payload.get("scope") != "EXQ001_CANDIDATE_SCOPE_V1":
        raise EXQCandidateReplayError("unsupported candidate qualification scope")
    if (
        payload.get("formal_pit_status") != "BLOCKED_DATA"
        or payload.get("formal_research_status") != "BLOCKED_DATA"
        or payload.get("csi500") != "NOT_STARTED"
    ):
        raise EXQCandidateReplayError("formal status boundary changed")
    domain_key_count = payload.get("domain_key_count")
    if not isinstance(domain_key_count, int) or domain_key_count < 1:
        raise EXQCandidateReplayError("candidate domain key count is invalid")
    domain_evidence = _mapping(payload.get("domain_evidence"), "domain_evidence")
    if set(domain_evidence) != set(REQUIRED_EVIDENCE):
        raise EXQCandidateReplayError(
            "candidate domain evidence keys differ from required contract"
        )
    domain_states = {name: _state(domain_evidence[name], name) for name in REQUIRED_EVIDENCE}
    domain_blocking = [name for name, state in domain_states.items() if state != VALID]
    rows = [_derive_row(row) for row in _records(payload.get("candidate_keys"), "candidate_keys")]
    keys = [_key(row) for row in rows]
    if len(set(keys)) != len(keys):
        raise EXQCandidateReplayError("duplicate candidate key")
    rows.sort(key=lambda row: _key(row))
    counts = Counter(str(row["disposition"]) for row in rows)
    status: QualificationStatus = "BLOCKED_DATA"
    if not counts["BLOCKED"] and not domain_blocking:
        status = (
            "QUALIFIED_WITH_EXCLUSIONS"
            if counts["EXCLUDED_T_KNOWN"]
            else "QUALIFIED_FOR_PORTFOLIO_RESEARCH"
        )
    residual = [row for row in rows if row["disposition"] == "BLOCKED"]
    return {
        "schema_version": 1,
        "kind": "candidate_scope_qualification_replay",
        "scope": "LIMITED_DEV_RESEARCH_CSI300_FROZEN_AF003_CANDIDATES_ONLY",
        "status": status,
        "matrix": rows,
        "residual": residual,
        "counts": {
            "candidate_keys": len(rows),
            "domain_key_count": domain_key_count,
            **dict(sorted(counts.items())),
        },
        "domain_evidence": domain_states,
        "domain_blocking_evidence": domain_blocking,
        "FORMAL_PIT_STATUS": "BLOCKED_DATA",
        "FORMAL_RESEARCH_STATUS": "BLOCKED_DATA",
        "CSI500": "NOT_STARTED",
        "provenance": {"input_sha256": dict(sorted(input_identities.items()))},
    }


def run(input_paths: dict[str, tuple[Path, str]]) -> dict[str, Any]:
    """Load separately pinned artifacts and replay their compiled candidate payload."""
    if set(input_paths) != {"compiled_scope", "legacy_qualification"}:
        raise EXQCandidateReplayError(
            "exact compiled scope and legacy qualification inputs required"
        )
    loaded = {name: _read_pinned_json(path, digest) for name, (path, digest) in input_paths.items()}
    legacy = loaded["legacy_qualification"]
    if (
        legacy.get("kind") != "candidate_scope_qualification"
        or legacy.get("status") != "BLOCKED_DATA"
    ):
        raise EXQCandidateReplayError("legacy EXQ baseline identity is invalid")
    return replay(
        loaded["compiled_scope"],
        {name: digest for name, (_, digest) in input_paths.items()},
    )


def persist(result: dict[str, Any], root: Path) -> dict[str, str]:
    """Persist the matrix, residual and summary independently by canonical content hash."""
    matrix = {"matrix": result["matrix"], "provenance": result["provenance"]}
    residual = {"residual": result["residual"], "provenance": result["provenance"]}
    summary = {key: value for key, value in result.items() if key not in {"matrix", "residual"}}
    return {
        "matrix_sha256": write_blob(root / "qualification_matrix", canonical(matrix)),
        "residual_sha256": write_blob(root / "qualification_residual", canonical(residual)),
        "summary_sha256": write_blob(root / "candidate_scope_qualification", canonical(summary)),
    }


def main() -> None:
    """Run an offline replay over two hash-pinned JSON inputs."""
    parser = argparse.ArgumentParser()
    parser.add_argument("--compiled-scope", type=Path, required=True)
    parser.add_argument("--compiled-scope-sha256", required=True)
    parser.add_argument("--legacy-qualification", type=Path, required=True)
    parser.add_argument("--legacy-qualification-sha256", required=True)
    parser.add_argument("--result-root", type=Path, required=True)
    args = parser.parse_args()
    result = run(
        {
            "compiled_scope": (args.compiled_scope, args.compiled_scope_sha256),
            "legacy_qualification": (args.legacy_qualification, args.legacy_qualification_sha256),
        }
    )
    print(json.dumps(persist(result, args.result_root), sort_keys=True))


if __name__ == "__main__":
    main()
