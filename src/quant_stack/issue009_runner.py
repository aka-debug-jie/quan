"""Single-use Issue 009 V2 walk-forward, robustness, and locked-test runner."""

from __future__ import annotations

import json
import statistics
from dataclasses import asdict
from datetime import date
from decimal import Decimal
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
from quant_stack.experiment_registry import register_experiment
from quant_stack.features import FeatureRow, calculate_features
from quant_stack.locked_test import LockedTestPrecommit, verify_locked_test_precommit
from quant_stack.models import DailyBar, Exchange, PriceBasis
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
    precommit = verify_locked_test_precommit(
        precommit_path, repository_root, data_root, qualification_path
    )
    run_directory = _claim_locked_attempt(artifact_root, precommit)
    destination = run_directory / "result.json"
    experiment_path = repository_root / precommit.experiment_config_path
    experiment = load_preregistered_experiment(experiment_path)
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
    )
    primary = _one_fold(
        accounting_open,
        accounting_close,
        raw_open,
        base_targets,
        locked_split,
        costs,
        1,
        benchmark_sessions,
    )
    doubled = _one_fold(
        accounting_open,
        accounting_close,
        raw_open,
        base_targets,
        locked_split,
        _doubled_costs(costs),
        1,
        benchmark_sessions,
    )
    delayed = _one_fold(
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
            fold = _one_fold(
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
    start_trimmed = _one_fold(
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
    end_trimmed = _one_fold(
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
    registry_ids = _register_all_runs(
        precommit,
        experiment_path,
        artifact_root / "experiment_registry",
        walk_folds,
        primary,
        doubled,
        delayed,
        neighbors,
        start_trimmed,
        end_trimmed,
    )
    outcome, evidence, diagnostics = _classify(
        experiment, walk_folds, primary, doubled, delayed, neighbors
    )
    oos_strategy, oos_benchmark = _concatenated_oos_curves(walk_folds)
    result: dict[str, object] = {
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
        "experiment_registry_ids": registry_ids,
    }
    result_id = _hash_json(result)
    result["result_id"] = result_id
    write_immutable(destination, _json_bytes(result) + b"\n")
    return destination, result


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
    write_immutable(run_directory / "attempt.json", _json_bytes(receipt) + b"\n")
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
) -> FoldEvaluation:
    return evaluate_walk_forward(
        accounting_open,
        accounting_close,
        targets,
        (split,),
        costs,
        delay,
        raw_open,
        benchmark_sessions,
    )[0]


def _register_all_runs(
    precommit: LockedTestPrecommit,
    experiment_path: Path,
    registry_root: Path,
    walk_folds: tuple[FoldEvaluation, ...],
    primary: FoldEvaluation,
    doubled: FoldEvaluation,
    delayed: FoldEvaluation,
    neighbors: list[dict[str, object]],
    start_trimmed: FoldEvaluation,
    end_trimmed: FoldEvaluation,
) -> list[str]:
    ids: list[str] = []
    config_hashes = {
        **precommit.config_hashes,
        precommit.experiment_config_path: sha256(experiment_path.read_bytes()).hexdigest(),
    }
    runs: list[tuple[str, dict[str, object]]] = [
        *(
            (f"WALK_FORWARD_BASE_FOLD_{index}", _fold_payload(fold))
            for index, fold in enumerate(walk_folds, 1)
        ),
        ("LOCKED_BASE_T1", _fold_payload(primary)),
        ("LOCKED_DOUBLE_COST_T1", _fold_payload(doubled)),
        ("LOCKED_BASE_T2", _fold_payload(delayed)),
        ("LOCKED_START_TRIM_21", _fold_payload(start_trimmed)),
        ("LOCKED_END_TRIM_21", _fold_payload(end_trimmed)),
    ]
    runs.extend(
        (
            f"LOCKED_NEIGHBOR_M{item['momentum_window_months']}_N{item['selection_count']}",
            _fold_payload(cast(FoldEvaluation, item["fold"])),
        )
        for item in neighbors
    )
    for run_kind, payload in runs:
        record_id, _ = register_experiment(
            registry_root,
            experiment_id=precommit.experiment_id,
            run_kind=run_kind,
            git_commit=precommit.code_commit,
            data_snapshot_id=precommit.data_snapshot_id,
            config_hashes=config_hashes,
            random_seed=precommit.random_seed,
            payload=payload,
        )
        ids.append(record_id)
    return ids


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
        "strategy_metrics": asdict(fold.strategy_metrics),
        "benchmark_metrics": asdict(fold.benchmark_metrics),
        "relative_metrics": asdict(fold.relative_metrics),
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
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str
    ).encode()
