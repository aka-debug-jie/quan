"""Strict result schema and immutable, computation-free result publication recovery."""

from __future__ import annotations

import json
import statistics
import traceback
from datetime import UTC, date, datetime
from decimal import Decimal, InvalidOperation
from hashlib import sha256
from pathlib import Path
from typing import Literal

import pandas as pd
from pydantic import BaseModel, ConfigDict, Field, model_validator

from quant_stack.experiment_registry import register_experiment
from quant_stack.research_json import canonical_json
from quant_stack.snapshot import write_immutable

Metric = float | Literal["POSITIVE_INFINITY", "NEGATIVE_INFINITY", "UNDEFINED"]
EvidenceScope = Literal["SYNTHETIC_ENGINEERING_ONLY", "RESEARCH", "CONTROLLED_RECOVERY_RESEARCH"]


class StrictResult(BaseModel):
    """Reject unknown fields, coercion and nonfinite JSON numbers."""

    model_config = ConfigDict(extra="forbid", strict=True, allow_inf_nan=False, frozen=True)


class Metrics(StrictResult):
    """Exact frozen performance metric names, with explicit undefined-ratio statuses."""

    cagr: float
    annualized_volatility: float
    sharpe_ratio: Metric
    maximum_drawdown: float
    sortino_ratio: Metric
    calmar_ratio: Metric
    total_return: float
    turnover: float
    total_transaction_costs: float
    rebalances: int
    time_in_market: float
    mean_cash_allocation: float
    maximum_cash_allocation: float
    worst_calendar_year: float
    best_calendar_year: float
    longest_drawdown_days: int


class Relative(StrictResult):
    """Frozen benchmark comparison fields."""

    excess_cagr: float
    sharpe_difference: Metric
    maximum_drawdown_difference: float
    annualized_tracking_error: float
    positive_excess_oos_fold_percentage: float


class Split(StrictResult):
    """Explicit date-only train and out-of-sample boundaries."""

    train_start: date
    train_end: date
    test_start: date
    test_end: date


class Curve(StrictResult):
    """Ordered date/value pairs and a content hash."""

    sha256: str
    points: list[tuple[date, float]]

    @model_validator(mode="after")
    def check_points(self) -> Curve:
        """Reject tampered, duplicated or unordered equity observations."""
        days = [point[0] for point in self.points]
        if not days or days != sorted(set(days)):
            raise ValueError("curve dates must be nonempty, unique and sorted")
        if sha256(canonical_json(self.points)).hexdigest() != self.sha256:
            raise ValueError("curve hash mismatch")
        return self


class Trade(StrictResult):
    """Decimal audit amounts are retained as exact decimal strings."""

    execution_date: date
    symbol: str
    notional: str
    transaction_cost: str
    raw_fill_price: str
    raw_quantity: str

    @model_validator(mode="after")
    def decimal_amounts(self) -> Trade:
        """Reject invalid or nonfinite decimal audit strings without losing precision."""
        try:
            values = [
                Decimal(getattr(self, field))
                for field in ("notional", "transaction_cost", "raw_fill_price", "raw_quantity")
            ]
        except InvalidOperation as error:
            raise ValueError("invalid decimal trade amount") from error
        if any(not value.is_finite() for value in values):
            raise ValueError("nonfinite decimal trade amount")
        if values[1] < 0 or values[2] <= 0:
            raise ValueError("invalid trade cost or raw fill price")
        return self


class FoldResult(StrictResult):
    """A complete serializable fold including fills and both equity curves."""

    split: Split
    strategy_metrics: Metrics
    benchmark_metrics: Metrics
    relative_metrics: Relative
    strategy_trade_count: int
    benchmark_trade_count: int
    strategy_trades: list[Trade]
    benchmark_trades: list[Trade]
    strategy_rejected_signal_dates: list[date]
    benchmark_rejected_signal_dates: list[date]
    strategy_equity: Curve
    benchmark_equity: Curve

    @model_validator(mode="after")
    def check_counts(self) -> FoldResult:
        """Validate counts, curve alignment and frozen OOS boundaries."""
        if self.strategy_trade_count != len(self.strategy_trades) or (
            self.benchmark_trade_count != len(self.benchmark_trades)
        ):
            raise ValueError("trade count mismatch")
        days = [point[0] for point in self.strategy_equity.points]
        if days != [point[0] for point in self.benchmark_equity.points]:
            raise ValueError("benchmark dates differ")
        if days[0] != self.split.test_start or days[-1] != self.split.test_end:
            raise ValueError("fold coverage differs from split")
        return self


class WalkResult(StrictResult):
    """All retained folds and aggregate OOS curves."""

    folds: list[FoldResult] = Field(min_length=1)
    median_fold_excess_return: float
    positive_excess_fold_percentage: float
    worst_fold: int
    best_fold: int
    concatenated_strategy_equity: Curve
    concatenated_benchmark_equity: Curve


class StepArtifact(StrictResult):
    """A fold checkpoint bound to its exact ordered execution plan."""

    schema_version: Literal["1.0.0"]
    precommit_id: str
    execution_plan_sha256: str
    ordinal: int
    run_name: str
    fold: FoldResult


class Neighbor(StrictResult):
    """One attempted frozen neighbor, never just the best configuration."""

    momentum_window_months: int
    selection_count: int
    result: FoldResult


class Robustness(StrictResult):
    """Exact predeclared decision inputs."""

    locked_test_net_cagr_exceeds_benchmark: bool
    locked_test_sharpe_exceeds_benchmark: bool
    locked_test_drawdown_not_worse: bool
    median_fold_excess_return_positive: bool
    positive_excess_fold_percentage_above_half: bool
    doubled_cost_excess_cagr_nonnegative: bool
    delayed_execution_excess_cagr_nonnegative: bool
    parameter_neighborhood_not_single_point_peak: bool
    not_driven_by_isolated_nonrepeatable_trades: bool
    research_integrity_valid: bool


class Diagnostics(StrictResult):
    """Frozen, finite decision diagnostics."""

    median_fold_excess_return: float
    positive_excess_fold_percentage: float
    worst_fold: int
    best_fold: int
    neighbor_excess_cagr: list[float]
    nonnegative_neighbor_count: int
    largest_three_positive_active_return_share: float


class ResearchResult(StrictResult):
    """V3 storage schema; this version does not amend the V2 research contract."""

    schema_version: Literal["3.0.0"]
    evidence_scope: EvidenceScope
    holdout_status: Literal["FRESH", "NOT_FRESH_PREVIOUSLY_ACCESSED", "NOT_APPLICABLE"]
    issue_gate_status: Literal[
        "PASS_CONTROLLED_RECOVERY",
        "PENDING_CONTROLLED_RECOVERY",
        "PENDING_RESEARCH",
        "SYNTHETIC_ENGINEERING_ONLY",
    ]
    fresh_holdout_status: Literal["AVAILABLE", "NOT_AVAILABLE", "NOT_APPLICABLE"]
    live_trading_authorization: Literal["FORBIDDEN"]
    predecessor_precommit_id: str | None
    controlled_reproduction_sha256: str | None
    experiment_id: str
    precommit_id: str
    data_snapshot_id: str
    code_commit: str
    outcome: Literal[
        "ROBUST_OUTPERFORMANCE_OBSERVED", "NO_EVIDENCE_OF_EDGE", "INVALID_RESEARCH_RESULT"
    ]
    research_integrity: Literal["PASS"]
    walk_forward: WalkResult
    locked_primary: FoldResult
    doubled_costs: FoldResult
    t2_execution: FoldResult
    parameter_neighborhood: list[Neighbor]
    start_trimmed: FoldResult
    end_trimmed: FoldResult
    robustness_evidence: Robustness
    diagnostics: Diagnostics
    experiment_registry_ids: list[str]

    @model_validator(mode="after")
    def validate_decision(self) -> ResearchResult:
        """Reject contradictory classification and OOS aggregation fields."""
        flags = self.robustness_evidence.model_dump()
        if not flags.pop("research_integrity_valid"):
            raise ValueError("PASS requires valid research integrity")
        expected_scope = {
            "SYNTHETIC_ENGINEERING_ONLY": (
                "NOT_APPLICABLE",
                "SYNTHETIC_ENGINEERING_ONLY",
                "NOT_APPLICABLE",
                None,
                None,
            ),
            "RESEARCH": ("FRESH", "PENDING_RESEARCH", "AVAILABLE", None, None),
        }.get(self.evidence_scope)
        observed_scope = (
            self.holdout_status,
            self.issue_gate_status,
            self.fresh_holdout_status,
            self.predecessor_precommit_id,
            self.controlled_reproduction_sha256,
        )
        controlled_valid = (
            self.evidence_scope == "CONTROLLED_RECOVERY_RESEARCH"
            and (
                self.holdout_status,
                self.fresh_holdout_status,
                self.predecessor_precommit_id,
            )
            == (
                "NOT_FRESH_PREVIOUSLY_ACCESSED",
                "NOT_AVAILABLE",
                "d1c3c371864885134f4a733cebdc09b0fedcd2ca69ad7a8a9c1898c4374fe7c6",
            )
            and (
                (
                    self.issue_gate_status == "PENDING_CONTROLLED_RECOVERY"
                    and self.controlled_reproduction_sha256 is None
                )
                or (
                    self.issue_gate_status == "PASS_CONTROLLED_RECOVERY"
                    and isinstance(self.controlled_reproduction_sha256, str)
                    and len(self.controlled_reproduction_sha256) == 64
                )
            )
        )
        if (
            not controlled_valid and observed_scope != expected_scope
        ) or self.live_trading_authorization != "FORBIDDEN":
            raise ValueError("research evidence scope fields are inconsistent")
        expected = (
            "ROBUST_OUTPERFORMANCE_OBSERVED" if all(flags.values()) else "NO_EVIDENCE_OF_EDGE"
        )
        if self.outcome != expected:
            raise ValueError("outcome contradicts frozen robustness evidence")
        folds = self.walk_forward.folds
        percentage = sum(
            fold.strategy_metrics.total_return > fold.benchmark_metrics.total_return
            for fold in folds
        ) / len(folds)
        if self.walk_forward.positive_excess_fold_percentage != percentage or any(
            fold.relative_metrics.positive_excess_oos_fold_percentage != percentage
            for fold in folds
        ):
            raise ValueError("inconsistent OOS aggregate percentage")
        if any(
            getattr(self.diagnostics, key) != getattr(self.walk_forward, key)
            for key in (
                "median_fold_excess_return",
                "positive_excess_fold_percentage",
                "worst_fold",
                "best_fold",
            )
        ):
            raise ValueError("diagnostics contradict walk-forward summary")
        fold_excess = [
            fold.strategy_metrics.total_return - fold.benchmark_metrics.total_return
            for fold in folds
        ]
        neighbors = [
            item.result.relative_metrics.excess_cagr for item in self.parameter_neighborhood
        ]
        expected_diagnostics = {
            "median_fold_excess_return": statistics.median(fold_excess),
            "neighbor_excess_cagr": neighbors,
            "nonnegative_neighbor_count": sum(value >= 0 for value in neighbors),
        }
        if any(
            getattr(self.diagnostics, key) != value for key, value in expected_diagnostics.items()
        ):
            raise ValueError("diagnostics are not derivable from retained runs")
        strategy = pd.Series(dict(self.locked_primary.strategy_equity.points), dtype=float)
        benchmark = pd.Series(dict(self.locked_primary.benchmark_equity.points), dtype=float)
        active = strategy.pct_change().iloc[1:] - benchmark.pct_change().iloc[1:]
        positives = active[active > 0]
        concentration = (
            float(positives.nlargest(3).sum() / positives.sum()) if not positives.empty else 1.0
        )
        if self.diagnostics.largest_three_positive_active_return_share != concentration:
            raise ValueError("isolated-return diagnostic is not derivable from retained curves")
        relative = self.locked_primary.relative_metrics
        expected_flags = {
            "locked_test_net_cagr_exceeds_benchmark": _metric_gt(relative.excess_cagr, 0),
            "locked_test_sharpe_exceeds_benchmark": _metric_gt(relative.sharpe_difference, 0),
            "locked_test_drawdown_not_worse": _metric_ge(relative.maximum_drawdown_difference, 0),
            "median_fold_excess_return_positive": statistics.median(fold_excess) > 0,
            "positive_excess_fold_percentage_above_half": percentage > 0.5,
            "doubled_cost_excess_cagr_nonnegative": _metric_ge(
                self.doubled_costs.relative_metrics.excess_cagr, 0
            ),
            "delayed_execution_excess_cagr_nonnegative": _metric_ge(
                self.t2_execution.relative_metrics.excess_cagr, 0
            ),
            "parameter_neighborhood_not_single_point_peak": (
                statistics.median(neighbors) >= 0 and sum(value >= 0 for value in neighbors) >= 3
            ),
            "not_driven_by_isolated_nonrepeatable_trades": (
                self.locked_primary.strategy_metrics.rebalances >= 12 and concentration < 0.5
            ),
            "research_integrity_valid": True,
        }
        if self.robustness_evidence.model_dump() != expected_flags:
            raise ValueError("robustness evidence is not derivable from retained results")
        return self


def _metric_gt(value: Metric, threshold: float) -> bool:
    """Apply a comparison to explicit finite/infinite metric states."""
    if value == "POSITIVE_INFINITY":
        return True
    if value in ("NEGATIVE_INFINITY", "UNDEFINED"):
        return False
    assert isinstance(value, float)
    return value > threshold


def _metric_ge(value: Metric, threshold: float) -> bool:
    """Apply an inclusive comparison to explicit finite/infinite metric states."""
    if value == "POSITIVE_INFINITY":
        return True
    if value in ("NEGATIVE_INFINITY", "UNDEFINED"):
        return False
    assert isinstance(value, float)
    return value >= threshold


class PublishedResearchResult(ResearchResult):
    """The actual final wire artifact, including a verified content identity."""

    result_id: str

    @model_validator(mode="after")
    def validate_identity(self) -> PublishedResearchResult:
        """Validate the hash of all fields except the hash itself."""
        if (
            self.evidence_scope == "CONTROLLED_RECOVERY_RESEARCH"
            and self.issue_gate_status != "PASS_CONTROLLED_RECOVERY"
        ):
            raise ValueError("controlled recovery cannot publish before reproduction passes")
        if (
            sha256(canonical_json(self.model_dump(mode="json", exclude={"result_id"}))).hexdigest()
            != self.result_id
        ):
            raise ValueError("published result identity mismatch")
        return self


def validate_fold(payload: object) -> None:
    """Validate the actual wire format, not a permissively coerced Python object."""
    FoldResult.model_validate_json(canonical_json(payload))


def save_failure(directory: Path, error: BaseException) -> None:
    """Append a failure receipt without overwriting prior attempts or results."""
    payload = {
        "schema_version": "1.0.0",
        "recorded_at": datetime.now(UTC),
        "status": "FAILED",
        "exception_type": type(error).__name__,
        "message": "Failure details are local diagnostics; no input values retained here.",
        "stack": [
            {"function": frame.name, "line": frame.lineno}
            for frame in traceback.extract_tb(error.__traceback__)
        ],
        "data_access_state": "POSSIBLY_ACCESSED",
        "phase": "PUBLICATION"
        if (directory / "prepared.json").exists()
        else "COMPUTATION_OR_VALIDATION",
        "attempt_sha256": sha256((directory / "attempt.json").read_bytes()).hexdigest()
        if (directory / "attempt.json").exists()
        else None,
        "completed_artifacts": {
            str(path.relative_to(directory)): sha256(path.read_bytes()).hexdigest()
            for path in sorted(directory.glob("steps/*.json"))
        },
        "recompute_authorized": False,
    }
    content = canonical_json(payload) + b"\n"
    write_immutable(directory / "failures" / f"{sha256(content).hexdigest()}.json", content)


def recover_publication(
    directory: Path, registry_root: Path, *, expected_sha256: str
) -> tuple[Path, dict[str, object]]:
    """Rehearse mechanical recovery; real research recovery requires a new frozen protocol."""
    content = (directory / "prepared.json").read_bytes()
    if sha256(content).hexdigest() != expected_sha256:
        raise ValueError("prepared result hash mismatch")
    envelope = Publication.model_validate_json(content)
    if envelope.result.evidence_scope != "SYNTHETIC_ENGINEERING_ONLY":
        raise ValueError("research recovery is not authorized by the existing V2 contract")
    try:
        return publish_prepared(directory, registry_root, expected_sha256=expected_sha256)
    except BaseException as error:
        save_failure(directory, error)
        raise


def recover_controlled_publication(
    parent: Path, registry_root: Path
) -> tuple[Path, dict[str, object]]:
    """Mechanically publish V3 only when its two complete builds were already anchored."""
    from quant_stack.locked_test import (
        RECOVERY_MODE,
        V3_AUTHORIZATION_PATH,
        _verify_v2_failure_archive,
        verify_controlled_recovery_authorization,
    )

    repository_root = parent.resolve().parents[3]
    authority = repository_root / "artifacts/issue009"
    authorization_path = repository_root / V3_AUTHORIZATION_PATH
    verified = verify_controlled_recovery_authorization(authorization_path, repository_root)
    authorization = json.loads(authorization_path.read_bytes())
    if (
        not isinstance(authorization, dict)
        or authorization.get("protocol_mode") != RECOVERY_MODE
        or parent.resolve()
        != (authority / "locked_runs" / str(authorization.get("precommit_id"))).resolve()
        or registry_root.resolve() != (authority / "experiment_registry").resolve()
        or verified.precommit_id != authorization.get("precommit_id")
    ):
        raise ValueError("controlled publication path differs from its V3 authorization")
    _verify_v2_failure_archive(repository_root)
    attempt = json.loads((parent / "attempt.json").read_bytes())
    child_receipt = (parent / "child_processes.json").read_bytes()
    expected_child = {
        "schema_version": "1.0.0",
        "precommit_id": authorization["precommit_id"],
        "build_exit_codes": {"build_a": 0, "build_b": 0},
        "retry_count": 0,
    }
    if (
        attempt.get("precommit_id") != authorization["precommit_id"]
        or json.loads(child_receipt) != expected_child
    ):
        raise ValueError("controlled recovery parent or child-process receipt is invalid")
    anchor_bytes = (parent / "publication_anchor.json").read_bytes()
    anchor = json.loads(anchor_bytes)
    expected_anchor = {
        "schema_version": "1.0.0",
        "precommit_id": authorization["precommit_id"],
        "reproduction_sha256": anchor.get("reproduction_sha256"),
        "child_processes_sha256": sha256(child_receipt).hexdigest(),
        "authorization_sha256": sha256(authorization_path.read_bytes()).hexdigest(),
    }
    if anchor != expected_anchor:
        raise ValueError("controlled recovery publication anchor is invalid")
    receipt_path = parent / "reproduction.json"
    receipt_bytes = receipt_path.read_bytes()
    if sha256(receipt_bytes).hexdigest() != anchor["reproduction_sha256"]:
        raise ValueError("controlled recovery reproduction receipt hash mismatch")
    receipt = json.loads(receipt_bytes)
    if not isinstance(receipt, dict) or receipt != {
        "authorized_build_count": 2,
        "build_a_prepared_sha256": receipt.get("build_a_prepared_sha256"),
        "build_b_prepared_sha256": receipt.get("build_b_prepared_sha256"),
        "data_snapshot_id": receipt.get("data_snapshot_id"),
        "evidence_scope": "CONTROLLED_RECOVERY_RESEARCH",
        "identical": True,
        "precommit_id": receipt.get("precommit_id"),
        "published_build": "build_a",
        "schema_version": "1.0.0",
        "status": "PREPARED_BYTES_IDENTICAL",
    }:
        raise ValueError("invalid controlled recovery reproduction receipt")
    first = parent / "build_a" / "prepared.json"
    second = parent / "build_b" / "prepared.json"
    first_bytes, second_bytes = first.read_bytes(), second.read_bytes()
    expected = receipt["build_a_prepared_sha256"]
    if (
        not isinstance(expected, str)
        or expected != receipt["build_b_prepared_sha256"]
        or sha256(first_bytes).hexdigest() != expected
        or sha256(second_bytes).hexdigest() != expected
        or first_bytes != second_bytes
    ):
        raise ValueError("controlled recovery prepared builds differ from their receipt")
    envelope, result, runs = _validate_prepared(first.parent, expected)
    _validate_prepared(second.parent, expected)
    if (
        envelope.result.evidence_scope != "CONTROLLED_RECOVERY_RESEARCH"
        or envelope.result.issue_gate_status != "PENDING_CONTROLLED_RECOVERY"
        or envelope.result.precommit_id != receipt["precommit_id"]
        or envelope.result.data_snapshot_id != receipt["data_snapshot_id"]
    ):
        raise ValueError("controlled recovery result identity differs from its receipt")
    result["issue_gate_status"] = "PASS_CONTROLLED_RECOVERY"
    result["controlled_reproduction_sha256"] = anchor["reproduction_sha256"]
    ResearchResult.model_validate_json(canonical_json(result))
    runs = result_runs(result)
    try:
        return _publish_validated(first.parent, registry_root, envelope, result, runs)
    except BaseException as error:
        save_failure(parent, error)
        raise


def prepare_publication(
    directory: Path, result: dict[str, object], config_hashes: dict[str, str], random_seed: int
) -> str:
    """Freeze a fully computed result before registry writes; return the recovery checksum."""
    ResearchResult.model_validate_json(canonical_json(result))
    plan_bytes = (directory / "execution_plan.json").read_bytes()
    steps = {
        path.name: sha256(path.read_bytes()).hexdigest()
        for path in sorted(directory.glob("steps/*.json"))
    }
    content = (
        canonical_json(
            {
                "schema_version": "1.0.0",
                "result": result,
                "config_hashes": config_hashes,
                "random_seed": random_seed,
                "execution_plan_sha256": sha256(plan_bytes).hexdigest(),
                "step_hashes": steps,
            }
        )
        + b"\n"
    )
    write_immutable(directory / "prepared.json", content)
    return sha256(content).hexdigest()


def _validate_prepared(
    directory: Path, expected_sha256: str
) -> tuple[Publication, dict[str, object], list[tuple[str, dict[str, object]]]]:
    """Validate every prepared identity and checkpoint without publishing it."""
    content = (directory / "prepared.json").read_bytes()
    if sha256(content).hexdigest() != expected_sha256:
        raise ValueError("prepared result hash mismatch")
    envelope = Publication.model_validate_json(content)
    plan_bytes = (directory / "execution_plan.json").read_bytes()
    if sha256(plan_bytes).hexdigest() != envelope.execution_plan_sha256:
        raise ValueError("execution plan hash mismatch")
    plan = ExecutionPlan.model_validate_json(plan_bytes)
    result = json.loads(canonical_json(envelope.result.model_dump(mode="json")))
    if result["experiment_registry_ids"]:
        raise ValueError("prepared result must precede registration")
    runs = result_runs(result)
    if set(plan.run_names) != {name for name, _ in runs}:
        raise ValueError("incomplete frozen run set")
    if (
        (plan.precommit_id, plan.code_commit, plan.data_snapshot_id, plan.evidence_scope)
        != (
            envelope.result.precommit_id,
            envelope.result.code_commit,
            envelope.result.data_snapshot_id,
            envelope.result.evidence_scope,
        )
        or plan.config_hashes != envelope.config_hashes
        or plan.random_seed != envelope.random_seed
    ):
        raise ValueError("publication identity differs from execution plan")
    if set(envelope.step_hashes) != {f"{i:03d}.json" for i in range(len(plan.run_names))}:
        raise ValueError("incomplete step checkpoints")
    run_map = dict(runs)
    for index, name in enumerate(plan.run_names):
        filename = f"{index:03d}.json"
        step_bytes = (directory / "steps" / filename).read_bytes()
        if sha256(step_bytes).hexdigest() != envelope.step_hashes[filename]:
            raise ValueError("step hash mismatch")
        checkpoint = StepArtifact.model_validate_json(step_bytes)
        if (checkpoint.precommit_id, checkpoint.execution_plan_sha256, checkpoint.ordinal) != (
            plan.precommit_id,
            envelope.execution_plan_sha256,
            index,
        ):
            raise ValueError("step identity differs from frozen plan")
        step = checkpoint.model_dump(mode="json")
        final_fold = json.loads(canonical_json(run_map[name]))
        if name.startswith("WALK_FORWARD_"):
            if step["fold"]["relative_metrics"]["positive_excess_oos_fold_percentage"] != 0.0:
                raise ValueError("provisional OOS aggregate must be zero before aggregation")
            step["fold"]["relative_metrics"].pop("positive_excess_oos_fold_percentage")
            final_fold["relative_metrics"].pop("positive_excess_oos_fold_percentage")
        if step["run_name"] != name or step["fold"] != final_fold:
            raise ValueError("prepared result differs from persisted step")
    return envelope, result, runs


def publish_prepared(
    directory: Path, registry_root: Path, *, expected_sha256: str
) -> tuple[Path, dict[str, object]]:
    """Recover publication only, from an explicitly pinned complete payload; never compute."""
    envelope, result, runs = _validate_prepared(directory, expected_sha256)
    if envelope.result.evidence_scope == "CONTROLLED_RECOVERY_RESEARCH":
        raise ValueError("controlled recovery requires its two-build receipt publication path")
    return _publish_validated(directory, registry_root, envelope, result, runs)


def _publish_validated(
    directory: Path,
    registry_root: Path,
    envelope: Publication,
    result: dict[str, object],
    runs: list[tuple[str, dict[str, object]]],
) -> tuple[Path, dict[str, object]]:
    """Register and publish an already validated complete result."""
    ids = []
    for kind, payload in runs:
        record_id, _ = register_experiment(
            registry_root,
            experiment_id=envelope.result.experiment_id,
            run_kind=kind,
            git_commit=envelope.result.code_commit,
            data_snapshot_id=envelope.result.data_snapshot_id,
            config_hashes=envelope.config_hashes,
            random_seed=envelope.random_seed,
            payload=payload,
            attempt_context={
                "precommit_id": envelope.result.precommit_id,
                "execution_plan_sha256": envelope.execution_plan_sha256,
                "schema_version": envelope.result.schema_version,
                "evidence_scope": envelope.result.evidence_scope,
            },
        )
        ids.append(record_id)
    result["experiment_registry_ids"] = ids
    ResearchResult.model_validate_json(canonical_json(result))
    result["result_id"] = sha256(canonical_json(result)).hexdigest()
    PublishedResearchResult.model_validate_json(canonical_json(result))
    destination = directory / "result.json"
    write_immutable(destination, canonical_json(result) + b"\n")
    return destination, result


class Publication(StrictResult):
    """Complete checksum-pinned publication envelope; partial runs cannot resume."""

    schema_version: Literal["1.0.0"]
    result: ResearchResult
    config_hashes: dict[str, str]
    random_seed: int
    execution_plan_sha256: str
    step_hashes: dict[str, str]


class ExecutionPlan(StrictResult):
    """Ordered computation identity written before input panels are opened."""

    precommit_id: str
    code_commit: str
    data_snapshot_id: str
    evidence_scope: EvidenceScope
    run_names: list[str]
    config_hashes: dict[str, str]
    random_seed: int
    runtime_environment: dict[str, str]
    parent_attempt_id: str | None = None
    predecessor_precommit_id: str | None = None
    authorized_builds: list[str] = Field(default_factory=list)
    holdout_status: str = "FRESH"

    @model_validator(mode="after")
    def unique_runs(self) -> ExecutionPlan:
        """Require an unambiguous nonempty frozen plan."""
        if not self.run_names or len(set(self.run_names)) != len(self.run_names):
            raise ValueError("execution plan requires unique runs")
        return self


def result_runs(result: dict[str, object]) -> list[tuple[str, dict[str, object]]]:
    """Enumerate every frozen run from the validated result schema."""
    parsed = ResearchResult.model_validate_json(canonical_json(result))
    runs = [
        (f"WALK_FORWARD_BASE_FOLD_{index}", fold.model_dump(mode="json"))
        for index, fold in enumerate(parsed.walk_forward.folds, 1)
    ]
    runs.extend(
        [
            ("LOCKED_BASE_T1", parsed.locked_primary.model_dump(mode="json")),
            ("LOCKED_DOUBLE_COST_T1", parsed.doubled_costs.model_dump(mode="json")),
            ("LOCKED_BASE_T2", parsed.t2_execution.model_dump(mode="json")),
            ("LOCKED_START_TRIM_21", parsed.start_trimmed.model_dump(mode="json")),
            ("LOCKED_END_TRIM_21", parsed.end_trimmed.model_dump(mode="json")),
        ]
    )
    runs.extend(
        (
            f"LOCKED_NEIGHBOR_M{item.momentum_window_months}_N{item.selection_count}",
            item.result.model_dump(mode="json"),
        )
        for item in parsed.parameter_neighborhood
    )
    if len({name for name, _ in runs}) != len(runs):
        raise ValueError("duplicate frozen run")
    return runs
