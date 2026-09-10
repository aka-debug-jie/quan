"""Single-use Issue 009 V2 walk-forward, robustness, and locked-test runner."""

from __future__ import annotations

import json
import math
import os
import statistics
import subprocess
import sys
from collections.abc import Callable
from dataclasses import asdict
from datetime import date
from decimal import Decimal
from functools import partial
from hashlib import sha256
from pathlib import Path
from typing import cast

import pandas as pd
import pyarrow.parquet as pq  # type: ignore[import-untyped]
import yaml

from quant_stack.costs import CostModel
from quant_stack.data.provider_series import load_provider_series
from quant_stack.evaluation import ResearchOutcome, RobustnessEvidence, classify_research_outcome
from quant_stack.evaluation_runner import FoldEvaluation, evaluate_walk_forward
from quant_stack.features import FeatureRow, calculate_features
from quant_stack.locked_test import RECOVERY_MODE, LockedTestPrecommit, verify_locked_test_precommit
from quant_stack.models import DailyBar, Exchange, PriceBasis
from quant_stack.research_json import canonical_json
from quant_stack.research_result import (
    EvidenceScope,
    ExecutionPlan,
    StepArtifact,
    prepare_publication,
    publish_prepared,
    recover_controlled_publication,
    save_failure,
)
from quant_stack.snapshot import write_immutable
from quant_stack.strategy import monthly_etf_momentum_targets
from quant_stack.walk_forward import WalkForwardSplit, load_preregistered_experiment


def run_issue009_locked_test(
    precommit_path: Path,
    repository_root: Path,
    data_root: Path,
    qualification_path: Path,
    artifact_root: Path,
) -> tuple[Path, dict[str, object]]:
    """Execute the precommitted protocol once and persist every run before classification."""
    if _declared_protocol_mode(precommit_path) == RECOVERY_MODE:
        raise ValueError("controlled recovery precommit requires the V3 recovery runner")
    authority = repository_root.resolve() / "artifacts/issue009"
    if artifact_root.resolve() != authority:
        raise ValueError("locked attempt authority must be repository artifacts/issue009")
    run_directory: Path | None = None

    def claim(precommit: LockedTestPrecommit) -> None:
        nonlocal run_directory
        run_directory = _claim_locked_attempt(authority, precommit)
        _freeze_execution_plan(precommit, repository_root, run_directory, "RESEARCH")

    try:
        precommit = verify_locked_test_precommit(
            precommit_path,
            repository_root,
            data_root,
            qualification_path,
            before_data_read=claim,
        )
        assert run_directory is not None
        return _execute_issue009(
            precommit,
            repository_root,
            data_root,
            artifact_root,
            run_directory,
            evidence_scope="RESEARCH",
        )
    except BaseException as error:
        if run_directory is not None:
            save_failure(run_directory, error)
        raise


def run_issue009_controlled_recovery(
    precommit_path: Path,
    repository_root: Path,
    data_root: Path,
    qualification_path: Path,
    artifact_root: Path,
) -> tuple[Path, dict[str, object]]:
    """Run exactly two preregistered builds and publish only after byte equality."""
    if _declared_protocol_mode(precommit_path) != RECOVERY_MODE:
        raise ValueError("V3 recovery runner requires a controlled recovery precommit")
    authority = repository_root.resolve() / "artifacts/issue009"
    if artifact_root.resolve() != authority:
        raise ValueError("locked attempt authority must be repository artifacts/issue009")
    parent: Path | None = None

    def claim(precommit: LockedTestPrecommit) -> None:
        nonlocal parent
        parent = _claim_locked_attempt(authority, precommit)
        for name in ("build_a", "build_b"):
            _freeze_execution_plan(
                precommit,
                repository_root,
                parent / name,
                "CONTROLLED_RECOVERY_RESEARCH",
            )

    try:
        precommit = verify_locked_test_precommit(
            precommit_path,
            repository_root,
            data_root,
            qualification_path,
            before_data_read=claim,
        )
        assert parent is not None
        environment = {
            **os.environ,
            "PYTHONHASHSEED": "0",
            "TZ": "UTC",
            "OMP_NUM_THREADS": "1",
            "OPENBLAS_NUM_THREADS": "1",
            "MKL_NUM_THREADS": "1",
            "NUMEXPR_NUM_THREADS": "1",
        }
        processes: list[tuple[str, subprocess.Popen[bytes]]] = []
        for name in ("build_a", "build_b"):
            command = (
                sys.executable,
                "-m",
                "quant_stack.controlled_build",
                "--precommit",
                str(precommit_path),
                "--repository-root",
                str(repository_root),
                "--data-root",
                str(data_root),
                "--qualification",
                str(qualification_path),
                "--build-directory",
                str(parent / name),
                "--build-name",
                name,
            )
            processes.append(
                (
                    name,
                    subprocess.Popen(
                        command,
                        cwd=repository_root,
                        env=environment,
                        stdout=subprocess.DEVNULL,
                        stderr=subprocess.DEVNULL,
                    ),
                )
            )
        exits = {name: process.wait() for name, process in processes}
        write_immutable(
            parent / "child_processes.json",
            canonical_json(
                {
                    "schema_version": "1.0.0",
                    "precommit_id": precommit.precommit_id,
                    "build_exit_codes": exits,
                    "retry_count": 0,
                }
            )
            + b"\n",
        )
        if exits != {"build_a": 0, "build_b": 0}:
            raise ValueError("one or more controlled recovery child builds failed")
        prepared = [parent / name / "prepared.json" for name in ("build_a", "build_b")]
        first_bytes, second_bytes = (path.read_bytes() for path in prepared)
        first_hash = sha256(first_bytes).hexdigest()
        second_hash = sha256(second_bytes).hexdigest()
        if first_bytes != second_bytes:
            raise ValueError("controlled recovery deterministic builds differ")
        reproduction = {
            "schema_version": "1.0.0",
            "status": "PREPARED_BYTES_IDENTICAL",
            "evidence_scope": "CONTROLLED_RECOVERY_RESEARCH",
            "precommit_id": precommit.precommit_id,
            "data_snapshot_id": precommit.data_snapshot_id,
            "build_a_prepared_sha256": first_hash,
            "build_b_prepared_sha256": second_hash,
            "identical": True,
            "authorized_build_count": 2,
            "published_build": "build_a",
        }
        write_immutable(parent / "reproduction.json", canonical_json(reproduction) + b"\n")
        reproduction_sha = sha256((parent / "reproduction.json").read_bytes()).hexdigest()
        child_sha = sha256((parent / "child_processes.json").read_bytes()).hexdigest()
        write_immutable(
            parent / "publication_anchor.json",
            canonical_json(
                {
                    "schema_version": "1.0.0",
                    "precommit_id": precommit.precommit_id,
                    "reproduction_sha256": reproduction_sha,
                    "child_processes_sha256": child_sha,
                    "authorization_sha256": sha256(precommit_path.read_bytes()).hexdigest(),
                }
            )
            + b"\n",
        )
        destination, published = recover_controlled_publication(
            parent, artifact_root / "experiment_registry"
        )
        pointer = {
            "schema_version": "1.0.0",
            "precommit_id": precommit.precommit_id,
            "result_relative_path": destination.relative_to(parent).as_posix(),
            "result_sha256": sha256(destination.read_bytes()).hexdigest(),
            "reproduction_sha256": reproduction_sha,
            "publication_anchor_sha256": sha256(
                (parent / "publication_anchor.json").read_bytes()
            ).hexdigest(),
        }
        write_immutable(parent / "result_pointer.json", canonical_json(pointer) + b"\n")
        return destination, published
    except BaseException as error:
        if parent is not None:
            save_failure(parent, error)
        raise


def run_issue009_controlled_build(
    precommit_path: Path,
    repository_root: Path,
    data_root: Path,
    qualification_path: Path,
    build_directory: Path,
    build_name: str,
) -> Path:
    """Execute one preauthorized child build without claiming or publishing."""
    if build_name not in ("build_a", "build_b"):
        raise ValueError("controlled recovery build name is not authorized")
    authority = repository_root.resolve() / "artifacts/issue009"
    precommit_id = json.loads(precommit_path.read_text(encoding="utf-8")).get("precommit_id")
    if not isinstance(precommit_id, str):
        raise ValueError("controlled recovery precommit lacks its identity")
    parent = authority / "locked_runs" / precommit_id
    if build_directory.resolve() != (parent / build_name).resolve():
        raise ValueError("controlled recovery build directory differs from its parent attempt")

    def validate_parent(precommit: LockedTestPrecommit) -> None:
        attempt = json.loads((parent / "attempt.json").read_bytes())
        if attempt.get("precommit_id") != precommit.precommit_id:
            raise ValueError("controlled recovery parent claim identity mismatch")
        expected = _freeze_execution_plan(
            precommit,
            repository_root,
            build_directory,
            "CONTROLLED_RECOVERY_RESEARCH",
        )
        observed = ExecutionPlan.model_validate_json(
            (build_directory / "execution_plan.json").read_bytes()
        )
        if observed != expected:
            raise ValueError("controlled recovery child plan mismatch")

    try:
        precommit = verify_locked_test_precommit(
            precommit_path,
            repository_root,
            data_root,
            qualification_path,
            before_data_read=validate_parent,
        )
        path, _ = _execute_issue009(
            precommit,
            repository_root,
            data_root,
            authority,
            build_directory,
            evidence_scope="CONTROLLED_RECOVERY_RESEARCH",
            publish_result=False,
        )
        return path
    except BaseException as error:
        save_failure(build_directory, error)
        raise


def _execute_issue009(
    precommit: LockedTestPrecommit,
    repository_root: Path,
    data_root: Path,
    artifact_root: Path,
    run_directory: Path,
    *,
    evidence_scope: EvidenceScope,
    publish_result: bool = True,
) -> tuple[Path, dict[str, object]]:
    """Shared computation pipeline; tests replace only the immutable input boundary."""
    completed = 0

    def save_fold(fold: FoldEvaluation) -> None:
        nonlocal completed
        payload = _fold_payload(fold)
        checkpoint = {
            "schema_version": "1.0.0",
            "precommit_id": precommit.precommit_id,
            "execution_plan_sha256": sha256(
                (run_directory / "execution_plan.json").read_bytes()
            ).hexdigest(),
            "ordinal": completed,
            "run_name": plan.run_names[completed],
            "fold": payload,
        }
        StepArtifact.model_validate_json(canonical_json(checkpoint))
        write_immutable(
            run_directory / "steps" / f"{completed:03d}.json",
            canonical_json(checkpoint) + b"\n",
        )
        completed += 1

    one_fold = partial(_one_fold, on_fold=save_fold)
    experiment_path = repository_root / precommit.experiment_config_path
    experiment = load_preregistered_experiment(experiment_path)
    plan = _freeze_execution_plan(precommit, repository_root, run_directory, evidence_scope)
    config_hashes = plan.config_hashes
    accounting_open, accounting_close, raw_open, feature_rows = _load_panels(precommit, data_root)
    signal_cutoff = pd.Timestamp(precommit.last_locked_signal_date)
    signal_index = cast(pd.DatetimeIndex, accounting_close.index)
    signal_index = signal_index[signal_index <= signal_cutoff]
    benchmark_sessions = tuple(signal_index.to_series().groupby(signal_index.to_period("M")).last())
    base = _mapping(experiment, "base_parameters")
    base_targets = _targets(
        signal_index,
        feature_rows,
        _integer(base, "momentum_window_months"),
        _integer(base, "selection_count"),
    )
    costs = _load_cost_model(repository_root / "configs/costs/cn_etf_v1.yaml")
    locked_split = WalkForwardSplit(
        accounting_close.index[0].date(),
        date.fromisoformat(precommit.selection_period_end),
        date.fromisoformat(precommit.locked_test_start),
        date.fromisoformat(precommit.locked_test_end),
    )
    selection_splits = _splits(experiment)
    walk_folds = evaluate_walk_forward(
        accounting_open,
        accounting_close,
        base_targets,
        selection_splits,
        costs,
        1,
        raw_open,
        benchmark_sessions,
        on_fold=save_fold,
    )
    primary = one_fold(
        accounting_open,
        accounting_close,
        raw_open,
        base_targets,
        locked_split,
        costs,
        1,
        benchmark_sessions,
    )
    doubled = one_fold(
        accounting_open,
        accounting_close,
        raw_open,
        base_targets,
        locked_split,
        _doubled_costs(costs),
        1,
        benchmark_sessions,
    )
    delayed = one_fold(
        accounting_open,
        accounting_close,
        raw_open,
        base_targets,
        locked_split,
        costs,
        2,
        benchmark_sessions,
    )
    grid = _mapping(experiment, "parameter_grid")
    neighbors: list[dict[str, object]] = []
    for momentum in _integer_list(grid, "momentum_windows_months"):
        for selection_count in _integer_list(grid, "selection_counts"):
            if momentum == _integer(base, "momentum_window_months") and selection_count == _integer(
                base, "selection_count"
            ):
                continue
            targets = _targets(signal_index, feature_rows, momentum, selection_count)
            fold = one_fold(
                accounting_open,
                accounting_close,
                raw_open,
                targets,
                locked_split,
                costs,
                1,
                benchmark_sessions,
            )
            neighbors.append(
                {
                    "momentum_window_months": momentum,
                    "selection_count": selection_count,
                    "fold": fold,
                }
            )
    sensitivity = _mapping(experiment, "start_end_sensitivity")
    locked_index = accounting_close.loc[
        pd.Timestamp(precommit.locked_test_start) : pd.Timestamp(precommit.locked_test_end)
    ].index
    start_trim = _integer(sensitivity, "start_trim_sessions")
    end_trim = _integer(sensitivity, "end_trim_sessions")
    start_trimmed = one_fold(
        accounting_open,
        accounting_close,
        raw_open,
        base_targets,
        WalkForwardSplit(
            locked_split.train_start,
            locked_split.train_end,
            locked_index[start_trim].date(),
            locked_split.test_end,
        ),
        costs,
        1,
        benchmark_sessions,
    )
    end_trimmed = one_fold(
        accounting_open,
        accounting_close,
        raw_open,
        base_targets,
        WalkForwardSplit(
            locked_split.train_start,
            locked_split.train_end,
            locked_split.test_start,
            locked_index[-end_trim - 1].date(),
        ),
        costs,
        1,
        benchmark_sessions,
    )
    outcome, evidence, diagnostics = _classify(
        experiment, walk_folds, primary, doubled, delayed, neighbors
    )
    oos_strategy, oos_benchmark = _concatenated_oos_curves(walk_folds)
    result: dict[str, object] = {
        "schema_version": "3.0.0",
        "evidence_scope": evidence_scope,
        "holdout_status": precommit.holdout_status
        if evidence_scope != "SYNTHETIC_ENGINEERING_ONLY"
        else "NOT_APPLICABLE",
        "issue_gate_status": (
            "PENDING_CONTROLLED_RECOVERY"
            if evidence_scope == "CONTROLLED_RECOVERY_RESEARCH"
            else "SYNTHETIC_ENGINEERING_ONLY"
            if evidence_scope == "SYNTHETIC_ENGINEERING_ONLY"
            else "PENDING_RESEARCH"
        ),
        "fresh_holdout_status": (
            "NOT_AVAILABLE"
            if evidence_scope == "CONTROLLED_RECOVERY_RESEARCH"
            else "NOT_APPLICABLE"
            if evidence_scope == "SYNTHETIC_ENGINEERING_ONLY"
            else "AVAILABLE"
        ),
        "live_trading_authorization": "FORBIDDEN",
        "predecessor_precommit_id": precommit.predecessor_precommit_id,
        "controlled_reproduction_sha256": None,
        "experiment_id": precommit.experiment_id,
        "precommit_id": precommit.precommit_id,
        "data_snapshot_id": precommit.data_snapshot_id,
        "code_commit": precommit.code_commit,
        "outcome": outcome.value,
        "research_integrity": "PASS",
        "walk_forward": {
            "folds": [_fold_payload(fold) for fold in walk_folds],
            "median_fold_excess_return": diagnostics["median_fold_excess_return"],
            "positive_excess_fold_percentage": diagnostics["positive_excess_fold_percentage"],
            "worst_fold": diagnostics["worst_fold"],
            "best_fold": diagnostics["best_fold"],
            "concatenated_strategy_equity": _series_payload(oos_strategy),
            "concatenated_benchmark_equity": _series_payload(oos_benchmark),
        },
        "locked_primary": _fold_payload(primary),
        "doubled_costs": _fold_payload(doubled),
        "t2_execution": _fold_payload(delayed),
        "parameter_neighborhood": [
            {
                "momentum_window_months": item["momentum_window_months"],
                "selection_count": item["selection_count"],
                "result": _fold_payload(cast(FoldEvaluation, item["fold"])),
            }
            for item in neighbors
        ],
        "start_trimmed": _fold_payload(start_trimmed),
        "end_trimmed": _fold_payload(end_trimmed),
        "robustness_evidence": asdict(evidence),
        "diagnostics": diagnostics,
        "experiment_registry_ids": [],
    }
    digest = prepare_publication(
        run_directory,
        result,
        config_hashes,
        precommit.random_seed,
    )
    if not publish_result:
        return run_directory / "prepared.json", result
    return publish_prepared(
        run_directory, artifact_root / "experiment_registry", expected_sha256=digest
    )


def _claim_locked_attempt(artifact_root: Path, precommit: LockedTestPrecommit) -> Path:
    """Atomically consume a precommit before any locked data is read; failures stay consumed."""
    parent = artifact_root / "locked_runs"
    parent.mkdir(parents=True, exist_ok=True)
    run_directory = parent / precommit.precommit_id
    try:
        run_directory.mkdir()
    except FileExistsError as error:
        raise ValueError("this locked-test precommit has already been attempted") from error
    receipt = {
        "status": "STARTED",
        "precommit_id": precommit.precommit_id,
        "code_commit": precommit.code_commit,
        "data_snapshot_id": precommit.data_snapshot_id,
    }
    try:
        write_immutable(run_directory / "attempt.json", _json_bytes(receipt) + b"\n")
    except BaseException as error:
        save_failure(run_directory, error)
        raise
    return run_directory


def _load_panels(
    precommit: LockedTestPrecommit, data_root: Path
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, dict[date, list[FeatureRow]]]:
    causal_by_symbol: dict[str, list[DailyBar]] = {}
    raw_by_symbol: dict[str, list[DailyBar]] = {}
    for asset in precommit.assets:
        manifest_path = data_root / "canonical" / "manifests" / f"{asset.causal_manifest_id}.json"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        output = data_root / manifest["output_file"]["relative_path"]
        causal_by_symbol[asset.symbol] = [_bar(row) for row in pq.read_table(output).to_pylist()]
        _, raw_by_symbol[asset.symbol] = load_provider_series(asset.raw_manifest_id, data_root)
        if [bar.trading_date for bar in causal_by_symbol[asset.symbol]] != [
            bar.trading_date for bar in raw_by_symbol[asset.symbol]
        ]:
            raise ValueError(f"raw and causal dates differ: {asset.symbol}")
    common_dates = sorted(
        set.intersection(
            *({bar.trading_date for bar in bars} for bars in causal_by_symbol.values())
        )
    )
    if not common_dates:
        raise ValueError("locked-test assets have no common sessions")
    symbols = tuple(sorted(causal_by_symbol))
    causal_maps = {
        symbol: {bar.trading_date: bar for bar in causal_by_symbol[symbol]} for symbol in symbols
    }
    raw_maps = {
        symbol: {bar.trading_date: bar for bar in raw_by_symbol[symbol]} for symbol in symbols
    }
    index = pd.DatetimeIndex(common_dates)
    accounting_open = pd.DataFrame(
        {
            symbol: [float(causal_maps[symbol][day].open) for day in common_dates]
            for symbol in symbols
        },
        index=index,
    )
    accounting_close = pd.DataFrame(
        {
            symbol: [float(causal_maps[symbol][day].close) for day in common_dates]
            for symbol in symbols
        },
        index=index,
    )
    raw_open = pd.DataFrame(
        {symbol: [float(raw_maps[symbol][day].open) for day in common_dates] for symbol in symbols},
        index=index,
    )
    features_by_date: dict[date, list[FeatureRow]] = {day: [] for day in common_dates}
    for symbol in symbols:
        for row in calculate_features(causal_by_symbol[symbol]):
            if row.bar.trading_date in features_by_date:
                features_by_date[row.bar.trading_date].append(row)
    if any(len(rows) != len(symbols) for rows in features_by_date.values()):
        raise ValueError("locked-test feature panel is incomplete")
    return accounting_open, accounting_close, raw_open, features_by_date


def _bar(row: dict[str, object]) -> DailyBar:
    return DailyBar(
        symbol=str(row["symbol"]),
        exchange=Exchange(str(row["exchange"])),
        price_basis=PriceBasis(str(row["price_basis"])),
        trading_date=cast(date, row["trading_date"]),
        open=Decimal(str(row["open"])),
        high=Decimal(str(row["high"])),
        low=Decimal(str(row["low"])),
        close=Decimal(str(row["close"])),
        volume=Decimal(str(row["volume"])),
    )


def _targets(
    signal_index: pd.DatetimeIndex,
    features_by_date: dict[date, list[FeatureRow]],
    momentum_months: int,
    selection_count: int,
) -> dict[pd.Timestamp, dict[str, Decimal]]:
    return monthly_etf_momentum_targets(
        signal_index, features_by_date, momentum_months, selection_count
    )


def _one_fold(
    accounting_open: pd.DataFrame,
    accounting_close: pd.DataFrame,
    raw_open: pd.DataFrame,
    targets: dict[pd.Timestamp, dict[str, Decimal]],
    split: WalkForwardSplit,
    costs: CostModel,
    delay: int,
    benchmark_sessions: tuple[pd.Timestamp, ...],
    *,
    on_fold: Callable[[FoldEvaluation], None] | None = None,
) -> FoldEvaluation:
    fold = evaluate_walk_forward(
        accounting_open,
        accounting_close,
        targets,
        (split,),
        costs,
        delay,
        raw_open,
        benchmark_sessions,
    )[0]
    if on_fold is not None:
        on_fold(fold)
    return fold


def _classify(
    experiment: dict[str, object],
    walk_folds: tuple[FoldEvaluation, ...],
    primary: FoldEvaluation,
    doubled: FoldEvaluation,
    delayed: FoldEvaluation,
    neighbors: list[dict[str, object]],
) -> tuple[ResearchOutcome, RobustnessEvidence, dict[str, object]]:
    fold_excess = [
        fold.strategy_metrics.total_return - fold.benchmark_metrics.total_return
        for fold in walk_folds
    ]
    neighbor_excess = [
        cast(FoldEvaluation, item["fold"]).relative_metrics.excess_cagr for item in neighbors
    ]
    neighbor_rule = _mapping(experiment, "parameter_neighborhood_rule")
    nonnegative_neighbors = sum(value >= 0 for value in neighbor_excess)
    neighborhood_pass = statistics.median(neighbor_excess) >= _number(
        neighbor_rule, "median_neighbor_excess_cagr_minimum"
    ) and nonnegative_neighbors >= _integer(neighbor_rule, "minimum_nonnegative_neighbors")
    isolated_rule = _mapping(experiment, "isolated_observation_rule")
    active = (
        primary.strategy.equity.pct_change().iloc[1:]
        - primary.benchmark.equity.pct_change().iloc[1:]
    )
    positives = active[active > 0]
    largest_count = _integer(isolated_rule, "largest_positive_active_days")
    concentration = (
        float(positives.nlargest(largest_count).sum() / positives.sum())
        if not positives.empty
        else 1.0
    )
    isolated_pass = primary.strategy.rebalances >= _integer(
        isolated_rule, "minimum_rebalances"
    ) and concentration < _number(isolated_rule, "maximum_positive_active_return_share")
    positive_percentage = sum(value > 0 for value in fold_excess) / len(fold_excess)
    evidence = RobustnessEvidence(
        locked_test_net_cagr_exceeds_benchmark=primary.relative_metrics.excess_cagr > 0,
        locked_test_sharpe_exceeds_benchmark=primary.relative_metrics.sharpe_difference > 0,
        locked_test_drawdown_not_worse=primary.relative_metrics.maximum_drawdown_difference >= 0,
        median_fold_excess_return_positive=statistics.median(fold_excess) > 0,
        positive_excess_fold_percentage_above_half=positive_percentage > 0.5,
        doubled_cost_excess_cagr_nonnegative=doubled.relative_metrics.excess_cagr >= 0,
        delayed_execution_excess_cagr_nonnegative=delayed.relative_metrics.excess_cagr >= 0,
        parameter_neighborhood_not_single_point_peak=neighborhood_pass,
        not_driven_by_isolated_nonrepeatable_trades=isolated_pass,
        research_integrity_valid=True,
    )
    ranked = sorted(range(len(fold_excess)), key=fold_excess.__getitem__)
    diagnostics: dict[str, object] = {
        "median_fold_excess_return": statistics.median(fold_excess),
        "positive_excess_fold_percentage": positive_percentage,
        "worst_fold": ranked[0] + 1,
        "best_fold": ranked[-1] + 1,
        "neighbor_excess_cagr": neighbor_excess,
        "nonnegative_neighbor_count": nonnegative_neighbors,
        "largest_three_positive_active_return_share": concentration,
    }
    return classify_research_outcome(evidence), evidence, diagnostics


def _concatenated_oos_curves(folds: tuple[FoldEvaluation, ...]) -> tuple[pd.Series, pd.Series]:
    return _concatenate([fold.strategy.equity for fold in folds]), _concatenate(
        [fold.benchmark.equity for fold in folds]
    )


def _concatenate(curves: list[pd.Series]) -> pd.Series:
    value = 100000.0
    values: list[float] = []
    dates: list[pd.Timestamp] = []
    for curve in curves:
        returns = curve.pct_change().fillna(0.0)
        for timestamp, daily_return in returns.items():
            value *= 1.0 + float(daily_return)
            dates.append(cast(pd.Timestamp, timestamp))
            values.append(value)
    return pd.Series(values, index=pd.DatetimeIndex(dates))


def _fold_payload(fold: FoldEvaluation) -> dict[str, object]:
    return {
        "split": asdict(fold.split),
        "strategy_metrics": _metric_payload(asdict(fold.strategy_metrics)),
        "benchmark_metrics": _metric_payload(asdict(fold.benchmark_metrics)),
        "relative_metrics": _metric_payload(asdict(fold.relative_metrics)),
        "strategy_trade_count": len(fold.strategy.trades),
        "benchmark_trade_count": len(fold.benchmark.trades),
        "strategy_trades": [_trade_payload(item) for item in fold.strategy.trades],
        "benchmark_trades": [_trade_payload(item) for item in fold.benchmark.trades],
        "strategy_rejected_signal_dates": [
            str(item.date()) for item in fold.strategy.rejected_signal_dates
        ],
        "benchmark_rejected_signal_dates": [
            str(item.date()) for item in fold.benchmark.rejected_signal_dates
        ],
        "strategy_equity": _series_payload(fold.strategy.equity),
        "benchmark_equity": _series_payload(fold.benchmark.equity),
    }


def _trade_payload(trade: object) -> dict[str, object]:
    from quant_stack.execution import SimulatedTrade

    if not isinstance(trade, SimulatedTrade):
        raise TypeError("locked result contains an unexpected trade type")
    return {
        "execution_date": str(trade.execution_date.date()),
        "symbol": trade.symbol,
        "notional": str(trade.notional),
        "transaction_cost": str(trade.transaction_cost),
        "raw_fill_price": str(trade.raw_fill_price),
        "raw_quantity": str(trade.raw_quantity),
    }


def _series_payload(series: pd.Series) -> dict[str, object]:
    return {
        "sha256": _series_hash(series),
        "points": [
            [str(cast(pd.Timestamp, timestamp).date()), float(value)]
            for timestamp, value in series.items()
        ],
    }


def _series_hash(series: pd.Series) -> str:
    return _hash_json(
        [
            [str(cast(pd.Timestamp, timestamp).date()), float(value)]
            for timestamp, value in series.items()
        ]
    )


def _load_cost_model(path: Path) -> CostModel:
    payload = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("cost config must be a mapping")
    return CostModel(
        commission_rate=Decimal(str(payload["commission_rate"])),
        minimum_commission=Decimal(str(payload["minimum_commission"])),
        half_spread_rate=Decimal(str(payload["half_spread_bps"])) / Decimal("10000"),
        slippage_rate=Decimal(str(payload["slippage_bps"])) / Decimal("10000"),
    )


def _doubled_costs(model: CostModel) -> CostModel:
    return CostModel(
        model.commission_rate * 2,
        model.minimum_commission * 2,
        model.half_spread_rate * 2,
        model.slippage_rate * 2,
    )


def _splits(experiment: dict[str, object]) -> tuple[WalkForwardSplit, ...]:
    raw = experiment.get("walk_forward_splits")
    if not isinstance(raw, list):
        raise ValueError("experiment requires walk-forward splits")
    return tuple(
        WalkForwardSplit(
            train_start=_date(item, "train_start"),
            train_end=_date(item, "train_end"),
            test_start=_date(item, "test_start"),
            test_end=_date(item, "test_end"),
        )
        for item in raw
        if isinstance(item, dict)
    )


def _mapping(mapping: dict[str, object], field: str) -> dict[str, object]:
    value = mapping.get(field)
    if not isinstance(value, dict):
        raise ValueError(f"experiment requires {field}")
    return {str(key): item for key, item in value.items()}


def _integer(mapping: dict[str, object], field: str) -> int:
    value = mapping.get(field)
    if not isinstance(value, int):
        raise ValueError(f"experiment requires integer {field}")
    return value


def _number(mapping: dict[str, object], field: str) -> float:
    value = mapping.get(field)
    if not isinstance(value, (int, float)):
        raise ValueError(f"experiment requires numeric {field}")
    return float(value)


def _integer_list(mapping: dict[str, object], field: str) -> list[int]:
    value = mapping.get(field)
    if not isinstance(value, list) or any(not isinstance(item, int) for item in value):
        raise ValueError(f"experiment requires integer list {field}")
    return value


def _date(mapping: dict[str, object], field: str) -> date:
    value = mapping.get(field)
    if isinstance(value, date):
        return value
    if isinstance(value, str):
        return date.fromisoformat(value)
    raise ValueError(f"experiment requires date {field}")


def _hash_json(value: object) -> str:
    return sha256(_json_bytes(value)).hexdigest()


def _json_bytes(value: object) -> bytes:
    return canonical_json(value)


def _metric_payload(values: dict[str, object]) -> dict[str, object]:
    """Represent undefined ratios explicitly without changing metric calculations."""
    return {
        key: (
            "UNDEFINED"
            if math.isnan(value)
            else "POSITIVE_INFINITY"
            if value > 0
            else "NEGATIVE_INFINITY"
        )
        if isinstance(value, float) and not math.isfinite(value)
        else value
        for key, value in values.items()
    }


def _expected_run_names(experiment: dict[str, object]) -> list[str]:
    base = _mapping(experiment, "base_parameters")
    grid = _mapping(experiment, "parameter_grid")
    return [
        *(f"WALK_FORWARD_BASE_FOLD_{i}" for i in range(1, len(_splits(experiment)) + 1)),
        "LOCKED_BASE_T1",
        "LOCKED_DOUBLE_COST_T1",
        "LOCKED_BASE_T2",
        *(
            f"LOCKED_NEIGHBOR_M{m}_N{n}"
            for m in _integer_list(grid, "momentum_windows_months")
            for n in _integer_list(grid, "selection_counts")
            if (m, n)
            != (_integer(base, "momentum_window_months"), _integer(base, "selection_count"))
        ),
        "LOCKED_START_TRIM_21",
        "LOCKED_END_TRIM_21",
    ]


def _freeze_execution_plan(
    precommit: LockedTestPrecommit,
    repository_root: Path,
    directory: Path,
    scope: EvidenceScope,
) -> ExecutionPlan:
    path = repository_root / precommit.experiment_config_path
    experiment = load_preregistered_experiment(path)
    run_names = _expected_run_names(experiment)
    if scope == "CONTROLLED_RECOVERY_RESEARCH" and tuple(run_names) != precommit.run_plan_names:
        raise ValueError("derived run plan differs from the controlled recovery authorization")
    plan = ExecutionPlan(
        precommit_id=precommit.precommit_id,
        code_commit=precommit.code_commit,
        data_snapshot_id=precommit.data_snapshot_id,
        evidence_scope=scope,
        run_names=run_names,
        config_hashes={
            **precommit.config_hashes,
            precommit.experiment_config_path: sha256(path.read_bytes()).hexdigest(),
        },
        random_seed=precommit.random_seed,
        runtime_environment=cast(dict[str, str], _mapping(experiment, "runtime_environment"))
        if scope == "CONTROLLED_RECOVERY_RESEARCH"
        else {},
        parent_attempt_id=(
            precommit.precommit_id if scope == "CONTROLLED_RECOVERY_RESEARCH" else None
        ),
        predecessor_precommit_id=(
            precommit.predecessor_precommit_id if scope == "CONTROLLED_RECOVERY_RESEARCH" else None
        ),
        authorized_builds=list(precommit.authorized_builds),
        holdout_status=precommit.holdout_status,
    )
    write_immutable(directory / "execution_plan.json", canonical_json(plan.model_dump()) + b"\n")
    return plan


def _declared_protocol_mode(path: Path) -> str:
    """Read only the precommit mode needed to select an authorized entrypoint."""
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("locked-test precommit must be a JSON object")
    mode = payload.get("protocol_mode", "fresh_holdout")
    if not isinstance(mode, str):
        raise ValueError("locked-test protocol mode must be a string")
    return mode
