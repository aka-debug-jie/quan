"""Offline safety tests for final EXQ-001 candidate qualification replay."""

from pathlib import Path
from typing import Any, cast

import pytest

from quant_stack_v2.exq_candidate_replay import EXQCandidateReplayError, replay
from quant_stack_v2.exq_current_evidence_compile import _ledger


def _payload() -> dict[str, Any]:
    evidence = {
        "raw_execution": "VALID",
        "corporate_actions": "VALID",
        "trading_status": "VALID",
        "price_limit": "VALID",
        "board_lot": "VALID",
        "t_plus_one": "VALID",
        "liquidity": "VALID",
        "cost_model": "VALID",
    }
    return {
        "schema_version": 1,
        "scope": "EXQ001_CANDIDATE_SCOPE_V1",
        "formal_pit_status": "BLOCKED_DATA",
        "formal_research_status": "BLOCKED_DATA",
        "csi500": "NOT_STARTED",
        "domain_key_count": 1,
        "domain_evidence": evidence.copy(),
        "candidate_keys": [
            {
                "symbol": "sz000001",
                "signal_session": "2020-01-02",
                "execution_session": "2020-01-03",
                "evidence": evidence,
            }
        ],
    }


def _row(payload: dict[str, Any]) -> dict[str, Any]:
    return cast(list[dict[str, Any]], payload["candidate_keys"])[0]


def test_complete_matrix_can_only_derive_qualified_status() -> None:
    result = replay(_payload(), {"compiled_scope": "a" * 64, "legacy_qualification": "b" * 64})
    assert result["status"] == "QUALIFIED_FOR_PORTFOLIO_RESEARCH"
    assert result["counts"] == {"candidate_keys": 1, "domain_key_count": 1, "QUALIFIED": 1}


def test_future_notice_cannot_create_an_exclusion() -> None:
    payload = _payload()
    row = _row(payload)
    row["evidence"]["trading_status"] = "MISSING"
    row["t_known_exclusion"] = {
        "status": "OFFICIAL_T_KNOWN_UNTRADABLE",
        "published_on": "2020-01-04",
    }
    with pytest.raises(EXQCandidateReplayError, match="future"):
        replay(payload, {"compiled_scope": "a" * 64, "legacy_qualification": "b" * 64})


def test_empty_provider_and_unreconciled_factor_remain_blocked() -> None:
    payload = _payload()
    row = _row(payload)
    row["evidence"]["raw_execution"] = "EMPTY_PROVIDER_RESPONSE"
    row["evidence"]["corporate_actions"] = "FACTOR_RECONCILIATION_PENDING"
    result = replay(payload, {"compiled_scope": "a" * 64, "legacy_qualification": "b" * 64})
    assert result["status"] == "BLOCKED_DATA"
    assert result["residual"][0]["blocking_evidence"] == ["raw_execution", "corporate_actions"]


def test_unchecked_full_domain_blocks_even_if_exact_residual_key_is_valid() -> None:
    payload = _payload()
    payload["domain_key_count"] = 100
    payload["domain_evidence"]["raw_execution"] = "MISSING"
    result = replay(payload, {"compiled_scope": "a" * 64, "legacy_qualification": "b" * 64})
    assert result["status"] == "BLOCKED_DATA"
    assert result["domain_blocking_evidence"] == ["raw_execution"]


def test_duplicate_key_is_rejected() -> None:
    payload = _payload()
    rows = cast(list[dict[str, Any]], payload["candidate_keys"])
    rows.append(rows[0])
    with pytest.raises(EXQCandidateReplayError, match="duplicate"):
        replay(payload, {"compiled_scope": "a" * 64, "legacy_qualification": "b" * 64})


def test_corporate_ledger_preserves_pending_factor_and_macro_boundaries() -> None:
    root = Path(__file__).parents[1]
    assert len(_ledger(root / "configs/v2/qualification/exq_001_corporate_ledger_v1.yaml")) == 64
