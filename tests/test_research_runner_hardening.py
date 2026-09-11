"""Offline end-to-end rehearsal: real features/execution/metrics, synthetic prices only."""

import json
import math
import os
import subprocess
import sys
from dataclasses import replace
from datetime import UTC, date, datetime, timedelta, timezone
from decimal import Decimal
from enum import Enum
from hashlib import sha256
from pathlib import Path
from unittest.mock import Mock

import numpy as np
import pandas as pd
import pytest
import yaml
from pydantic import ValidationError

from quant_stack import issue009_runner as runner
from quant_stack import research_result as storage
from quant_stack.features import calculate_features
from quant_stack.locked_test import LockedTestPrecommit
from quant_stack.models import DailyBar, Exchange, PriceBasis
from quant_stack.research_json import canonical_json
from quant_stack.research_result import ResearchResult, publish_prepared
from quant_stack.snapshot import write_immutable

REPOSITORY = Path(__file__).resolve().parents[1]


@pytest.fixture(autouse=True)
def forbid_network(monkeypatch):
    """The rehearsal cannot depend on any live service, including accidental downloads."""
    import socket

    def reject(*args, **kwargs):
        raise AssertionError("network forbidden in synthetic research rehearsal")

    monkeypatch.setattr(socket.socket, "connect", reject)
    monkeypatch.setattr(socket.socket, "connect_ex", reject)
    monkeypatch.setattr(socket, "create_connection", reject)


def synthetic_precommit() -> LockedTestPrecommit:
    """No real precommit, snapshot or data identity is consumed by these tests."""
    return LockedTestPrecommit(
        precommit_id="a" * 64,
        version="1.0.0",
        status="LOCKED_TEST_PRECOMMIT",
        experiment_id="synthetic_rehearsal",
        code_commit="synthetic-code",
        tracked_tree_sha256="b" * 64,
        data_snapshot_id="c" * 64,
        qualification_report_id="d" * 64,
        qualification_report_sha256="d" * 64,
        source_registry_sha256="e" * 64,
        source_registry_path="synthetic.yaml",
        experiment_config_path="configs/experiments/etf_walk_forward_v2.yaml",
        experiment_config_sha256="f" * 64,
        config_hashes={"synthetic": "f" * 64},
        walk_forward_split_sha256="1" * 64,
        selection_period_end="2023-12-29",
        locked_test_start="2024-01-02",
        locked_test_end="2026-09-09",
        last_locked_signal_date="2026-08-31",
        random_seed=0,
        assets=(),
    )


def controlled_synthetic_precommit() -> LockedTestPrecommit:
    """Use exact V3 governance identities with synthetic code/input placeholders."""
    from quant_stack import locked_test

    precommit = replace(
        synthetic_precommit(),
        precommit_id="",
        experiment_config_path=locked_test.V3_EXPERIMENT_PATH,
        experiment_config_sha256=locked_test.V3_EXPERIMENT_SHA256,
        protocol_mode=locked_test.RECOVERY_MODE,
        version=locked_test.RECOVERY_PRECOMMIT_VERSION,
        status="CONTROLLED_RECOVERY_PRECOMMIT",
        data_snapshot_id=locked_test.V2_DATA_SNAPSHOT_ID,
        predecessor_precommit_id=locked_test.V2_PRECOMMIT_ID,
        predecessor_precommit_file_sha256=locked_test.V2_PRECOMMIT_FILE_SHA256,
        predecessor_attempt_sha256=locked_test.V2_ATTEMPT_SHA256,
        predecessor_failure_sha256=locked_test.V2_FAILURE_SHA256,
        qualification_report_id=locked_test.V2_QUALIFICATION_ID,
        qualification_report_sha256=locked_test.V2_QUALIFICATION_ID,
        walk_forward_split_sha256=locked_test.V2_WALK_FORWARD_SPLIT_SHA256,
        run_plan_names=tuple(locked_test._AUTHORIZED_RECOVERY_RUNS),
        holdout_status="NOT_FRESH_PREVIOUSLY_ACCESSED",
        authorized_builds=("build_a", "build_b"),
    )
    identity = precommit.as_dict()
    identity.pop("precommit_id")
    return replace(precommit, precommit_id=sha256(canonical_json(identity)).hexdigest())


def setup_controlled_repository(root: Path) -> tuple[LockedTestPrecommit, Path]:
    """Create only the contract/config/cost/predecessor bytes needed by synthetic V3 tests."""
    from quant_stack import locked_test

    precommit = controlled_synthetic_precommit()
    for relative in (
        locked_test.V3_EXPERIMENT_PATH,
        "configs/costs/cn_etf_v1.yaml",
        "configs/experiments/LOCKED_TEST_PRECOMMIT_V2.json",
    ):
        destination = root / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes((REPOSITORY / relative).read_bytes())
    old = root / "artifacts/issue009/locked_runs" / locked_test.V2_PRECOMMIT_ID
    old.mkdir(parents=True)
    attempt = (
        b'{"code_commit":"10275b30e82f9d3b394e4ffc2de1c5138dc31965",'
        b'"data_snapshot_id":"6f33e58c7681a3444d05933d7605672a22940ca5a5039b748d962c419fea4750",'
        b'"precommit_id":"d1c3c371864885134f4a733cebdc09b0fedcd2ca69ad7a8a9c1898c4374fe7c6",'
        b'"status":"STARTED"}\n'
    )
    failure = (
        b'{"attempt_status":"FAILED","code_commit":"10275b30e82f9d3b394e4ffc2de1c5138dc31965",'
        b'"data_snapshot_id":"6f33e58c7681a3444d05933d7605672a22940ca5a5039b748d962c419fea4750",'
        b'"error_message":"Object of type date is not JSON serializable","error_type":"TypeError",'
        b'"execution_commit":"a9b96c01ddf713e2860c175f674aae2bf2f93453",'
        b'"failure_stage":"experiment_registry_serialization","locked_data_accessed":true,'
        b'"metrics_persisted":false,"outcome":"INVALID_RESEARCH_RESULT",'
        b'"precommit_id":"d1c3c371864885134f4a733cebdc09b0fedcd2ca69ad7a8a9c1898c4374fe7c6",'
        b'"rerun_permitted":false}\n'
    )
    assert sha256(attempt).hexdigest() == locked_test.V2_ATTEMPT_SHA256
    assert sha256(failure).hexdigest() == locked_test.V2_FAILURE_SHA256
    (old / "attempt.json").write_bytes(attempt)
    (old / "failure.json").write_bytes(failure)
    authorization = root / locked_test.V3_AUTHORIZATION_PATH
    authorization.parent.mkdir(parents=True, exist_ok=True)
    authorization.write_bytes(canonical_json(precommit.as_dict()))
    return precommit, authorization


@pytest.fixture(scope="module")
def panels():
    """Generate oscillating synthetic ETF bars, including full feature warm-up."""
    return synthetic_panels()


def synthetic_panels():
    """Return the complete deterministic synthetic research panel."""
    index = pd.bdate_range("2015-01-05", "2026-09-09")
    features = {day.date(): [] for day in index}
    columns = {}
    for offset, symbol in enumerate(("SYN_A", "SYN_B", "SYN_C")):
        prices = [
            10 + i * 0.003 + math.sin(i / 17 + offset) + 0.2 * math.sin(i / 2.3)
            for i in range(len(index))
        ]
        columns[symbol] = prices
        bars = [
            DailyBar(
                symbol=symbol,
                exchange=Exchange.SSE,
                price_basis=PriceBasis.CAUSAL_ADJUSTED,
                trading_date=day.date(),
                open=Decimal(str(price)),
                close=Decimal(str(price)),
                high=Decimal(str(price + 0.1)),
                low=Decimal(str(price - 0.1)),
                volume=Decimal("100000"),
            )
            for day, price in zip(index, prices, strict=True)
        ]
        for row in calculate_features(bars):
            features[row.bar.trading_date].append(row)
    close = pd.DataFrame(columns, index=index)
    return close * 0.999, close, close * 0.999, features


def execute(tmp_path, monkeypatch, panels):
    monkeypatch.setattr(runner, "_load_panels", lambda *_: panels)
    precommit = synthetic_precommit()
    directory = runner._claim_locked_attempt(tmp_path, precommit)
    return runner._execute_issue009(
        precommit,
        REPOSITORY,
        tmp_path / "no-real-data",
        tmp_path,
        directory,
        evidence_scope="SYNTHETIC_ENGINEERING_ONLY",
    )


def test_strict_json_types_and_stability():
    class Kind(Enum):
        DAILY = "daily"

    value = {
        "day": date(2020, 1, 2),
        "timestamp": datetime(2020, 1, 2, 8, tzinfo=timezone(timedelta(hours=8))),
        "decimal": Decimal("1.5200"),
        "kind": Kind.DAILY,
        "path": Path("evidence/a.pdf"),
        "number": np.int64(3),
        "float": np.float64(1.25),
        "bool": np.bool_(True),
    }
    result = json.loads(canonical_json(value))
    assert result["timestamp"] == datetime(2020, 1, 2, tzinfo=UTC).isoformat()
    assert result["decimal"] == "1.5200"
    assert canonical_json(value) == canonical_json(result)


@pytest.mark.parametrize("value", [object(), {1: "invalid"}, {1, 2}, np.array([1])])
def test_unknown_types_fail_closed(value):
    with pytest.raises(TypeError):
        canonical_json(value)


@pytest.mark.parametrize("value", [float("nan"), float("inf"), Decimal("NaN"), datetime.now()])
def test_nonfinite_and_naive_datetime_fail_closed(value):
    with pytest.raises(ValueError):
        canonical_json(value)


def test_synthetic_full_pipeline_roundtrip_and_reproduction(tmp_path, monkeypatch, panels):
    before = panels[2].copy(deep=True)
    first_path, first = execute(tmp_path / "first", monkeypatch, panels)
    second_path, second = execute(tmp_path / "independent-rebuild", monkeypatch, panels)
    assert first_path.read_bytes() == second_path.read_bytes()
    storage.PublishedResearchResult.model_validate_json(first_path.read_bytes())
    assert first == second
    assert first["evidence_scope"] == "SYNTHETIC_ENGINEERING_ONLY"
    assert len(first["experiment_registry_ids"]) == 16
    assert len(list((first_path.parent / "steps").glob("*.json"))) == 16
    assert len(first["walk_forward"]["folds"]) == 6
    assert len(first["parameter_neighborhood"]) == 5
    write_immutable(
        tmp_path / "reproduction.json",
        canonical_json(
            {
                "evidence_scope": "SYNTHETIC_ENGINEERING_ONLY",
                "synthetic_raw_panel_sha256": sha256(panels[2].to_csv().encode()).hexdigest(),
                "first_output_sha256": sha256(first_path.read_bytes()).hexdigest(),
                "rebuilt_output_sha256": sha256(second_path.read_bytes()).hexdigest(),
                "identical": True,
                "source_hashes": {
                    str(path.relative_to(REPOSITORY)): sha256(path.read_bytes()).hexdigest()
                    for path in sorted((REPOSITORY / "src/quant_stack").rglob("*.py"))
                },
                "experiment_config_sha256": sha256(
                    (REPOSITORY / synthetic_precommit().experiment_config_path).read_bytes()
                ).hexdigest(),
            }
        )
        + b"\n",
    )
    result_id = first.pop("result_id")
    assert sha256(canonical_json(first)).hexdigest() == result_id
    parsed = ResearchResult.model_validate_json(canonical_json(first))
    assert canonical_json(parsed.model_dump(mode="json")) == canonical_json(first)
    pd.testing.assert_frame_equal(before, panels[2])
    for fold in parsed.walk_forward.folds:
        assert fold.strategy_trade_count > 0
        assert fold.benchmark_trade_count > 0
        assert fold.strategy_metrics.total_transaction_costs > 0
    for mutate in (
        lambda x: x.update(unexpected=True),
        lambda x: x.pop("locked_primary"),
        lambda x: x["locked_primary"]["strategy_metrics"].update(cagr="1.0"),
        lambda x: x["locked_primary"].update(strategy_trade_count=-1),
        lambda x: x["locked_primary"]["strategy_equity"].update(sha256="bad"),
        lambda x: x.update(outcome="INVALID_RESEARCH_RESULT"),
        lambda x: x["robustness_evidence"].update(
            locked_test_net_cagr_exceeds_benchmark=not x["robustness_evidence"][
                "locked_test_net_cagr_exceeds_benchmark"
            ]
        ),
    ):
        invalid = json.loads(canonical_json(first))
        mutate(invalid)
        with pytest.raises((ValidationError, ValueError)):
            ResearchResult.model_validate_json(canonical_json(invalid))


def test_recover_publication_without_recomputing(tmp_path, monkeypatch, panels):
    original = storage.register_experiment
    calls = 0

    def fail_third(*args, **kwargs):
        nonlocal calls
        calls += 1
        if calls == 3:
            raise OSError("synthetic registry failure")
        return original(*args, **kwargs)

    monkeypatch.setattr(storage, "register_experiment", fail_third)
    with pytest.raises(OSError, match="synthetic registry failure"):
        execute(tmp_path, monkeypatch, panels)
    directory = tmp_path / "locked_runs" / synthetic_precommit().precommit_id
    assert not (directory / "result.json").exists()
    assert len(list((directory / "steps").glob("*.json"))) == 16
    prepared_hash = sha256((directory / "prepared.json").read_bytes()).hexdigest()
    monkeypatch.setattr(storage, "register_experiment", original)
    no_compute = Mock(side_effect=AssertionError("recovery must not compute"))
    monkeypatch.setattr(runner, "evaluate_walk_forward", no_compute)
    monkeypatch.setattr(runner, "_load_panels", no_compute)
    path, result = storage.recover_publication(
        directory, tmp_path / "experiment_registry", expected_sha256=prepared_hash
    )
    assert len(result["experiment_registry_ids"]) == 16
    original_bytes = path.read_bytes()
    publish_prepared(directory, tmp_path / "experiment_registry", expected_sha256=prepared_hash)
    assert path.read_bytes() == original_bytes
    no_compute.assert_not_called()
    with pytest.raises(ValueError, match="hash mismatch"):
        publish_prepared(directory, tmp_path / "experiment_registry", expected_sha256="bad")
    # Tampering is confined to disposable synthetic fixtures.
    step = directory / "steps/000.json"
    step.write_bytes(step.read_bytes() + b" ")
    with pytest.raises(ValueError, match="step hash mismatch"):
        publish_prepared(directory, tmp_path / "experiment_registry", expected_sha256=prepared_hash)


def test_research_recovery_is_not_retroactively_authorized(tmp_path, monkeypatch, panels):
    path, _ = execute(tmp_path, monkeypatch, panels)
    prepared = path.parent / "prepared.json"
    payload = json.loads(prepared.read_bytes())
    payload["result"]["evidence_scope"] = "RESEARCH"
    payload["result"].update(
        holdout_status="FRESH",
        issue_gate_status="PENDING_RESEARCH",
        fresh_holdout_status="AVAILABLE",
        predecessor_precommit_id=None,
    )
    plan_path = path.parent / "execution_plan.json"
    plan = json.loads(plan_path.read_bytes())
    plan["evidence_scope"] = "RESEARCH"
    plan.update(
        holdout_status="FRESH",
        parent_attempt_id=None,
        predecessor_precommit_id=None,
    )
    plan_path.write_bytes(canonical_json(plan))
    payload["execution_plan_sha256"] = sha256(plan_path.read_bytes()).hexdigest()
    prepared.write_bytes(canonical_json(payload))
    with pytest.raises(ValueError, match="not authorized"):
        storage.recover_publication(
            path.parent,
            tmp_path / "registry",
            expected_sha256=sha256(prepared.read_bytes()).hexdigest(),
        )


def test_new_precommit_cannot_replay_consumed_interval(tmp_path):
    from quant_stack.locked_test import verify_locked_test_precommit

    for identity in ("a" * 64, "b" * 64):
        precommit = replace(synthetic_precommit(), precommit_id=identity, code_commit=identity)
        path = tmp_path / "precommit.json"
        path.write_bytes(canonical_json(precommit.as_dict()))
        with pytest.raises(ValueError, match="interval is consumed"):
            verify_locked_test_precommit(path, tmp_path, tmp_path / "absent", tmp_path / "absent")


def test_positive_single_fold_saves_final_aggregation(panels):
    from quant_stack.costs import CostModel
    from quant_stack.walk_forward import WalkForwardSplit

    index = pd.bdate_range("2024-01-02", periods=65)
    prices = pd.DataFrame({"A": np.linspace(10, 20, len(index)), "B": 10.0}, index=index)
    saved = []
    fold = runner._one_fold(
        prices,
        prices,
        prices,
        {index[0]: {"A": Decimal("1"), "B": Decimal("0"), "CASH": Decimal("0")}},
        WalkForwardSplit(date(2020, 1, 1), date(2023, 12, 29), index[0].date(), index[-1].date()),
        CostModel(Decimal("0"), Decimal("0"), Decimal("0"), Decimal("0")),
        1,
        (index[0],),
        on_fold=saved.append,
    )
    assert fold.relative_metrics.positive_excess_oos_fold_percentage == 1.0
    assert runner._fold_payload(saved[0]) == runner._fold_payload(fold)


@pytest.mark.parametrize("cash", ["112.8571428571428571428571429", "100000.1428571428571428571429"])
def test_decimal_affordability_retains_frozen_costs(cash):
    from quant_stack.costs import CostModel, trade_cost
    from quant_stack.execution import _affordable_notional, simulate_target_weights

    model = CostModel(Decimal("0.0006"), Decimal("10"), Decimal("0.0004"), Decimal("0.0006"))
    initial = Decimal(cash)
    bound = _affordable_notional(initial, model)
    expected = bound.next_minus() if bound + trade_cost(bound, model) > initial else bound
    index = pd.bdate_range("2024-01-02", periods=2)
    prices = pd.DataFrame({"A": [10.0, 10.0]}, index=index)
    result = simulate_target_weights(
        prices,
        prices,
        {index[0]: {"A": Decimal("1"), "CASH": Decimal("0")}},
        model,
        initial_cash=initial,
    )
    fill = result.trades[0]
    assert fill.notional == expected
    assert fill.transaction_cost == trade_cost(fill.notional, model)
    assert fill.notional + fill.transaction_cost <= initial
    assert fill.raw_quantity == fill.notional / fill.raw_fill_price
    assert result.cash_weights.min() >= 0


def test_claim_write_failure_is_retained_and_consumed(tmp_path, monkeypatch):
    def fail(*args):
        raise OSError("synthetic claim write failure")

    monkeypatch.setattr(runner, "write_immutable", fail)
    with pytest.raises(OSError, match="claim write failure"):
        runner._claim_locked_attempt(tmp_path, synthetic_precommit())
    directory = tmp_path / "locked_runs" / synthetic_precommit().precommit_id
    receipt = json.loads(next((directory / "failures").glob("*.json")).read_bytes())
    assert receipt["attempt_sha256"] is None
    with pytest.raises(ValueError, match="already been attempted"):
        runner._claim_locked_attempt(tmp_path, synthetic_precommit())


def test_two_fresh_python_processes_rebuild_identical_results(tmp_path):
    worker = Path(__file__).with_name("subprocess_synthetic_build.py")
    environment = {
        **os.environ,
        "PYTHONHASHSEED": "0",
        "TZ": "UTC",
        "NO_PROXY": "*",
    }
    processes = [
        subprocess.Popen(
            (sys.executable, str(worker), str(tmp_path / name)),
            cwd=REPOSITORY,
            env=environment,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
        )
        for name in ("process_a", "process_b")
    ]
    completed = [process.communicate(timeout=120) for process in processes]
    assert [process.returncode for process in processes] == [0, 0], completed
    paths = [
        tmp_path / name / "locked_runs" / synthetic_precommit().precommit_id / "result.json"
        for name in ("process_a", "process_b")
    ]
    assert paths[0].read_bytes() == paths[1].read_bytes()


def test_v3_recovery_declaration_and_precommit_are_exactly_bounded():
    from quant_stack import locked_test

    config = yaml.safe_load(
        (REPOSITORY / "configs/experiments/etf_walk_forward_v3.yaml").read_text()
    )
    assert (
        sha256((REPOSITORY / locked_test.V3_EXPERIMENT_PATH).read_bytes()).hexdigest()
        == locked_test.V3_EXPERIMENT_SHA256
    )
    locked_test._controlled_recovery(config)
    bounded = replace(
        synthetic_precommit(),
        protocol_mode=locked_test.RECOVERY_MODE,
        version=locked_test.RECOVERY_PRECOMMIT_VERSION,
        status="CONTROLLED_RECOVERY_PRECOMMIT",
        data_snapshot_id=locked_test.V2_DATA_SNAPSHOT_ID,
        predecessor_precommit_id=locked_test.V2_PRECOMMIT_ID,
        predecessor_precommit_file_sha256=locked_test.V2_PRECOMMIT_FILE_SHA256,
        predecessor_attempt_sha256=locked_test.V2_ATTEMPT_SHA256,
        predecessor_failure_sha256=locked_test.V2_FAILURE_SHA256,
        qualification_report_id=locked_test.V2_QUALIFICATION_ID,
        qualification_report_sha256=locked_test.V2_QUALIFICATION_ID,
        walk_forward_split_sha256=locked_test.V2_WALK_FORWARD_SPLIT_SHA256,
        run_plan_names=tuple(locked_test._AUTHORIZED_RECOVERY_RUNS),
        holdout_status="NOT_FRESH_PREVIOUSLY_ACCESSED",
        authorized_builds=("build_a", "build_b"),
    )
    locked_test._validate_recovery_precommit_identity(bounded)
    with pytest.raises(ValueError, match="exceeds"):
        locked_test._validate_recovery_precommit_identity(
            replace(bounded, locked_test_end="2026-09-10")
        )
    config["ordered_run_names"] = config["ordered_run_names"][:-1]
    with pytest.raises(ValueError, match="ordered run plan"):
        locked_test._controlled_recovery(config)


def test_controlled_child_builds_and_receipt_only_publication(tmp_path, monkeypatch, panels):
    from quant_stack import locked_test

    precommit, authorization = setup_controlled_repository(tmp_path)
    parent = tmp_path / "artifacts/issue009/locked_runs" / precommit.precommit_id
    runner._claim_locked_attempt(tmp_path / "artifacts/issue009", precommit)
    for name in precommit.authorized_builds:
        runner._freeze_execution_plan(
            precommit, tmp_path, parent / name, "CONTROLLED_RECOVERY_RESEARCH"
        )

    def synthetic_verify(*args, before_data_read):
        before_data_read(precommit)
        return precommit

    monkeypatch.setattr(runner, "verify_locked_test_precommit", synthetic_verify)
    monkeypatch.setattr(runner, "_load_panels", lambda *_: panels)
    prepared = [
        runner.run_issue009_controlled_build(
            authorization,
            tmp_path,
            tmp_path / "no-real-data",
            tmp_path / "d0",
            parent / name,
            name,
        )
        for name in precommit.authorized_builds
    ]
    assert prepared[0].read_bytes() == prepared[1].read_bytes()
    prepared_hash = sha256(prepared[0].read_bytes()).hexdigest()
    child = (
        canonical_json(
            {
                "schema_version": "1.0.0",
                "precommit_id": precommit.precommit_id,
                "build_exit_codes": {"build_a": 0, "build_b": 0},
                "retry_count": 0,
            }
        )
        + b"\n"
    )
    write_immutable(parent / "child_processes.json", child)
    reproduction = (
        canonical_json(
            {
                "schema_version": "1.0.0",
                "status": "PREPARED_BYTES_IDENTICAL",
                "evidence_scope": "CONTROLLED_RECOVERY_RESEARCH",
                "precommit_id": precommit.precommit_id,
                "data_snapshot_id": precommit.data_snapshot_id,
                "build_a_prepared_sha256": prepared_hash,
                "build_b_prepared_sha256": prepared_hash,
                "identical": True,
                "authorized_build_count": 2,
                "published_build": "build_a",
            }
        )
        + b"\n"
    )
    write_immutable(parent / "reproduction.json", reproduction)
    write_immutable(
        parent / "publication_anchor.json",
        canonical_json(
            {
                "schema_version": "1.0.0",
                "precommit_id": precommit.precommit_id,
                "reproduction_sha256": sha256(reproduction).hexdigest(),
                "child_processes_sha256": sha256(child).hexdigest(),
                "authorization_sha256": sha256(authorization.read_bytes()).hexdigest(),
            }
        )
        + b"\n",
    )
    monkeypatch.setattr(
        locked_test, "verify_controlled_recovery_authorization", lambda *_: precommit
    )
    path, result = storage.recover_controlled_publication(
        parent, tmp_path / "artifacts/issue009/experiment_registry"
    )
    assert result["issue_gate_status"] == "PASS_CONTROLLED_RECOVERY"
    assert result["fresh_holdout_status"] == "NOT_AVAILABLE"
    storage.PublishedResearchResult.model_validate_json(path.read_bytes())
    with pytest.raises(ValueError, match="two-build receipt"):
        storage.publish_prepared(
            parent / "build_a", tmp_path / "other", expected_sha256=prepared_hash
        )


def test_controlled_parent_launches_both_children_and_fails_closed(tmp_path, monkeypatch):
    precommit, authorization = setup_controlled_repository(tmp_path)

    def synthetic_verify(*args, before_data_read):
        before_data_read(precommit)
        return precommit

    exits = iter((0, 1))
    launched = []

    class Process:
        def __init__(self, command, **kwargs):
            launched.append(command)
            self.code = next(exits)

        def wait(self):
            return self.code

    monkeypatch.setattr(runner, "verify_locked_test_precommit", synthetic_verify)
    monkeypatch.setattr(runner.subprocess, "Popen", Process)
    with pytest.raises(ValueError, match="child builds failed"):
        runner.run_issue009_controlled_recovery(
            authorization,
            tmp_path,
            tmp_path / "data",
            tmp_path / "d0",
            tmp_path / "artifacts/issue009",
        )
    assert len(launched) == 2
    parent = tmp_path / "artifacts/issue009/locked_runs" / precommit.precommit_id
    assert not (parent / "reproduction.json").exists()
    assert next((parent / "failures").glob("*.json")).is_file()


def test_controlled_authorization_rejects_non_self_hash_before_publication(tmp_path):
    from quant_stack import locked_test

    _, authorization = setup_controlled_repository(tmp_path)
    payload = json.loads(authorization.read_bytes())
    payload["code_commit"] = "tampered"
    authorization.write_bytes(canonical_json(payload))
    with pytest.raises(ValueError, match="content hash mismatch"):
        locked_test.verify_controlled_recovery_authorization(authorization, tmp_path)


def test_partial_checkpoint_and_failure_receipt(tmp_path, monkeypatch, panels):
    monkeypatch.setattr(runner, "_load_panels", lambda *_: panels)
    precommit = replace(synthetic_precommit(), experiment_config_path="experiment.yaml")
    (tmp_path / "experiment.yaml").write_bytes(
        (REPOSITORY / synthetic_precommit().experiment_config_path).read_bytes()
    )
    costs = tmp_path / "configs/costs"
    costs.mkdir(parents=True)
    (costs / "cn_etf_v1.yaml").write_bytes(
        (REPOSITORY / "configs/costs/cn_etf_v1.yaml").read_bytes()
    )

    def synthetic_verify(*args, before_data_read):
        before_data_read(precommit)
        return precommit

    monkeypatch.setattr(runner, "verify_locked_test_precommit", synthetic_verify)
    original = runner.write_immutable

    def fail_second(path, content):
        if path.name == "001.json":
            raise OSError("synthetic step write failure")
        return original(path, content)

    monkeypatch.setattr(runner, "write_immutable", fail_second)
    authority = tmp_path / "artifacts/issue009"
    (tmp_path / "synthetic.json").write_bytes(canonical_json(precommit.as_dict()))
    with pytest.raises(OSError, match="synthetic step write failure"):
        runner.run_issue009_locked_test(
            tmp_path / "synthetic.json", tmp_path, tmp_path / "no-data", tmp_path / "d0", authority
        )
    directory = authority / "locked_runs" / precommit.precommit_id
    assert len(list((directory / "steps").glob("*.json"))) == 1
    failure = json.loads(next((directory / "failures").glob("*.json")).read_bytes())
    assert failure["exception_type"] == "OSError"
    assert len(failure["completed_artifacts"]) == 1
    assert not (directory / "prepared.json").exists()
    with pytest.raises(FileNotFoundError):
        publish_prepared(directory, tmp_path / "registry", expected_sha256="bad")
    with pytest.raises(ValueError, match="already been attempted"):
        runner.run_issue009_locked_test(
            tmp_path / "synthetic.json", tmp_path, tmp_path / "no-data", tmp_path / "d0", authority
        )
    with pytest.raises(ValueError, match="authority"):
        runner.run_issue009_locked_test(
            tmp_path / "synthetic.json",
            tmp_path,
            tmp_path / "no-data",
            tmp_path / "d0",
            tmp_path / "different-root",
        )
