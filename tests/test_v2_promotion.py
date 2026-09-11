"""Offline fail-closed tests for V2-010 through V2-014 contracts."""

from __future__ import annotations

from decimal import Decimal

import pytest

from quant_stack_v2.champion import CandidateEvidence, select_champions
from quant_stack_v2.external_validation import (
    ExternalValidationError,
    create_external_blind_test_precommit,
    qualify_external_market,
)
from quant_stack_v2.lean_reconciliation import EngineState, reconcile_lean_fixture
from quant_stack_v2.paper import V2PaperError, initialize_v2_paper_account, require_v2_paper_run
from quant_stack_v2.rd_agent import RDAgentError, RDProposal, validate_rd_proposal


def _state(*, cash: str = "100", nav: str = "100") -> EngineState:
    return EngineState(
        "2024-01-02",
        ("order-1",),
        ("fill-1",),
        Decimal(cash),
        (("SPY", Decimal("1")),),
        Decimal(nav),
        Decimal("0"),
        Decimal("1"),
    )


def _candidate(
    strategy_id: str, *, sharpe: str = "1.0", qualified: bool = True
) -> CandidateEvidence:
    return CandidateEvidence(
        strategy_id=strategy_id,
        market="GLOBAL_ETF_USD",
        currency="USD",
        data_qualified=qualified,
        pit_qualified=qualified,
        external_test_passed=qualified,
        reproducible=qualified,
        lean_reconciled=qualified,
        net_return=Decimal("0.20"),
        net_sharpe=Decimal(sharpe),
        maximum_drawdown=Decimal("-0.10"),
        benchmark_net_return=Decimal("0.10"),
        benchmark_sharpe=Decimal("0.50"),
        benchmark_maximum_drawdown=Decimal("-0.10"),
        data_sha256="a" * 64,
        config_sha256="b" * 64,
        code_commit="c" * 40,
    )


def test_external_qualification_blocks_pending_source_and_currency_mix() -> None:
    blocked = qualify_external_market(
        dataset_id="global_etf_usd_external_v1",
        market="GLOBAL_ETF_USD",
        currency="USD",
        source_approval="PENDING_SOURCE_APPROVAL",
    )
    assert blocked.status == "BLOCKED_DATA"
    forged = qualify_external_market(
        dataset_id="global_etf_usd_external_v1",
        market="GLOBAL_ETF_USD",
        currency="USD",
        source_approval="APPROVED",
    )
    assert forged.status == "BLOCKED_DATA"
    assert "raw_manifest_missing" in forged.reasons
    with pytest.raises(ExternalValidationError, match="QUALIFIED"):
        create_external_blind_test_precommit(
            blocked,
            strategy_id="v2-a",
            input_manifest_sha256="a" * 64,
            code_commit="b" * 40,
            config_sha256="c" * 64,
            split_sha256="d" * 64,
            benchmark_id="benchmark",
        )
    with pytest.raises(ExternalValidationError, match="currency"):
        qualify_external_market(
            dataset_id="bad", market="CSI500_CNY", currency="USD", source_approval="APPROVED"
        )


def test_lean_reconciliation_requires_fixture_and_locates_first_difference() -> None:
    blocked = reconcile_lean_fixture((_state(),), None, fixture_sha256=None)
    assert blocked.status == "BLOCKED_ENGINE"
    mismatch = reconcile_lean_fixture((_state(),), (_state(cash="99"),), fixture_sha256="a" * 64)
    assert mismatch.first_difference == "index:0:session:2024-01-02:field:cash"
    assert (
        reconcile_lean_fixture((_state(),), (_state(),), fixture_sha256="a" * 64).status == "PASS"
    )


def test_champion_selection_is_strict_and_limited_to_two(tmp_path) -> None:
    registry = select_champions(
        (
            _candidate("a", sharpe="1.0"),
            _candidate("b", sharpe="2.0"),
            _candidate("c", sharpe="3.0"),
            _candidate("bad", qualified=False),
        )
    )
    winners = [item.strategy_id for item in registry.decisions if item.status == "PAPER_CANDIDATE"]
    assert winners == ["b", "c"]
    assert (
        next(item for item in registry.decisions if item.strategy_id == "bad").status
        == "REJECTED_NO_EDGE"
    )
    account = initialize_v2_paper_account(
        registry, candidate_id="b", currency="USD", artifact_root=tmp_path / "artifacts/v2/paper"
    )
    assert account.database_path.is_file()
    with pytest.raises(V2PaperError, match="qualified raw"):
        require_v2_paper_run(
            registry,
            candidate_id="b",
            currency="USD",
            raw_qualified=False,
            corporate_actions_qualified=True,
            cost_model_qualified=True,
        )
    with pytest.raises(V2PaperError, match="PAPER_CANDIDATE"):
        initialize_v2_paper_account(
            registry,
            candidate_id="bad",
            currency="USD",
            artifact_root=tmp_path / "artifacts/v2/paper",
        )


def test_rd_agent_refuses_execution_capabilities() -> None:
    proposal = RDProposal(
        1,
        "hypothesis",
        ("raw-qualified",),
        ("momentum",),
        "return",
        "chronological",
        "frozen-cost",
        ("overfit",),
        ("no-edge",),
        (),
    )
    validate_rd_proposal(proposal)
    with pytest.raises(RDAgentError, match="forbidden"):
        validate_rd_proposal(
            RDProposal(
                1,
                "hypothesis",
                ("raw-qualified",),
                ("momentum",),
                "return",
                "chronological",
                "frozen-cost",
                ("overfit",),
                ("no-edge",),
                ("train",),
            )
        )
