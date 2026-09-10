"""Walk-forward evaluation orchestration over supplied, immutable daily input panels."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from decimal import Decimal
from typing import cast

import pandas as pd

from quant_stack.benchmarks import natural_month_end_sessions, same_universe_equal_weight_targets
from quant_stack.costs import CostModel
from quant_stack.evaluation import (
    ExecutionStatistics,
    PerformanceMetrics,
    RelativeMetrics,
    compare_to_primary_benchmark,
    evaluate_equity_curve,
)
from quant_stack.execution import TargetWeightSimulation, simulate_target_weights
from quant_stack.walk_forward import WalkForwardSplit


@dataclass(frozen=True)
class FoldEvaluation:
    """One independently retained OOS fold and its frozen primary-benchmark comparison."""

    split: WalkForwardSplit
    strategy: TargetWeightSimulation
    benchmark: TargetWeightSimulation
    strategy_metrics: PerformanceMetrics
    benchmark_metrics: PerformanceMetrics
    relative_metrics: RelativeMetrics


def evaluate_walk_forward(
    open_prices: pd.DataFrame,
    close_prices: pd.DataFrame,
    strategy_targets: Mapping[pd.Timestamp, Mapping[str, Decimal]],
    splits: tuple[WalkForwardSplit, ...],
    cost_model: CostModel,
    execution_delay_sessions: int = 1,
    execution_audit_prices: pd.DataFrame | None = None,
    benchmark_rebalance_sessions: tuple[pd.Timestamp, ...] | None = None,
    on_fold: Callable[[FoldEvaluation], None] | None = None,
) -> tuple[FoldEvaluation, ...]:
    """Evaluate every frozen OOS fold without optimizing, filtering, or joining fold results."""
    folds: list[FoldEvaluation] = []
    benchmark_sessions = benchmark_rebalance_sessions or natural_month_end_sessions(
        cast(pd.DatetimeIndex, open_prices.index)
    )
    for split in splits:
        open_fold, close_fold = _fold_prices(open_prices, close_prices, split)
        audit_fold = (
            execution_audit_prices.loc[open_fold.index]
            if execution_audit_prices is not None
            else open_fold
        )
        strategy_fold_targets = {
            timestamp: target
            for timestamp, target in strategy_targets.items()
            if timestamp in open_fold.index
        }
        benchmark_targets = same_universe_equal_weight_targets(
            (session for session in benchmark_sessions if session in open_fold.index),
            tuple(open_fold.columns),
        )
        strategy = simulate_target_weights(
            open_fold,
            close_fold,
            strategy_fold_targets,
            cost_model,
            execution_delay_sessions,
            execution_audit_prices=audit_fold,
        )
        benchmark = simulate_target_weights(
            open_fold,
            close_fold,
            benchmark_targets,
            cost_model,
            execution_delay_sessions,
            execution_audit_prices=audit_fold,
        )
        strategy_metrics = evaluate_equity_curve(strategy.equity, _execution_statistics(strategy))
        benchmark_metrics = evaluate_equity_curve(
            benchmark.equity, _execution_statistics(benchmark)
        )
        folds.append(
            FoldEvaluation(
                split,
                strategy,
                benchmark,
                strategy_metrics,
                benchmark_metrics,
                compare_to_primary_benchmark(
                    strategy.equity,
                    benchmark.equity,
                    strategy_metrics,
                    benchmark_metrics,
                    0.0,
                ),
            )
        )
        if on_fold is not None:
            on_fold(folds[-1])
    positive_percentage = _positive_excess_fold_percentage(folds)
    return tuple(
        FoldEvaluation(
            fold.split,
            fold.strategy,
            fold.benchmark,
            fold.strategy_metrics,
            fold.benchmark_metrics,
            compare_to_primary_benchmark(
                fold.strategy.equity,
                fold.benchmark.equity,
                fold.strategy_metrics,
                fold.benchmark_metrics,
                positive_percentage,
            ),
        )
        for fold in folds
    )


def _fold_prices(
    open_prices: pd.DataFrame, close_prices: pd.DataFrame, split: WalkForwardSplit
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Select exactly one frozen OOS date interval, rejecting coverage incompatibility."""
    start = pd.Timestamp(split.test_start)
    end = pd.Timestamp(split.test_end)
    open_fold = open_prices.loc[start:end]
    close_fold = close_prices.loc[start:end]
    if open_fold.empty or open_fold.index[0] != start or open_fold.index[-1] != end:
        raise ValueError("frozen OOS split is incompatible with supplied price coverage")
    return open_fold, close_fold


def _execution_statistics(simulation: TargetWeightSimulation) -> ExecutionStatistics:
    """Derive reportable execution aggregates from the immutable simulated trade list."""
    cash = simulation.cash_weights
    return ExecutionStatistics(
        turnover=simulation.turnover,
        total_transaction_costs=simulation.total_transaction_costs,
        rebalances=simulation.rebalances,
        time_in_market=float((cash < 1.0).mean()),
        mean_cash_allocation=float(cash.mean()),
        maximum_cash_allocation=float(cash.max()),
    )


def _positive_excess_fold_percentage(folds: list[FoldEvaluation]) -> float:
    """Return the retained-fold fraction with positive net total-return excess."""
    if not folds:
        raise ValueError("walk-forward evaluation requires at least one frozen OOS fold")
    return sum(
        fold.strategy_metrics.total_return > fold.benchmark_metrics.total_return for fold in folds
    ) / len(folds)
