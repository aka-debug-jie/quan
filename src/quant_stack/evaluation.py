"""Deterministic, net-of-cost performance statistics for frozen experiments."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

import pandas as pd

TRADING_DAYS_PER_YEAR = 252


@dataclass(frozen=True)
class ExecutionStatistics:
    """Execution aggregates supplied by the auditable simulation ledger."""

    turnover: float
    total_transaction_costs: float
    rebalances: int
    time_in_market: float
    mean_cash_allocation: float
    maximum_cash_allocation: float


@dataclass(frozen=True)
class PerformanceMetrics:
    """Required net-of-cost metrics for one daily equity curve."""

    cagr: float
    annualized_volatility: float
    sharpe_ratio: float
    maximum_drawdown: float
    sortino_ratio: float
    calmar_ratio: float
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


@dataclass(frozen=True)
class RelativeMetrics:
    """Strategy metrics measured against the frozen primary benchmark."""

    excess_cagr: float
    sharpe_difference: float
    maximum_drawdown_difference: float
    annualized_tracking_error: float
    positive_excess_oos_fold_percentage: float


class ResearchOutcome(StrEnum):
    """The only allowed classifications for a frozen research result."""

    ROBUST_OUTPERFORMANCE_OBSERVED = "ROBUST_OUTPERFORMANCE_OBSERVED"
    NO_EVIDENCE_OF_EDGE = "NO_EVIDENCE_OF_EDGE"
    INVALID_RESEARCH_RESULT = "INVALID_RESEARCH_RESULT"


@dataclass(frozen=True)
class RobustnessEvidence:
    """Predeclared evidence needed for an outcome classification."""

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


def evaluate_equity_curve(equity: pd.Series, execution: ExecutionStatistics) -> PerformanceMetrics:
    """Calculate frozen 252-day, zero-risk-free metrics from a daily net equity curve."""
    _validate_equity(equity)
    returns = equity.pct_change().iloc[1:]
    periods = len(returns)
    total_return = equity.iloc[-1] / equity.iloc[0] - 1.0
    cagr = (equity.iloc[-1] / equity.iloc[0]) ** (TRADING_DAYS_PER_YEAR / periods) - 1.0
    annualized_volatility = returns.std(ddof=0) * (TRADING_DAYS_PER_YEAR**0.5)
    sharpe = _annualized_ratio(returns, downside_only=False)
    sortino = _annualized_ratio(returns, downside_only=True)
    drawdowns = equity / equity.cummax() - 1.0
    maximum_drawdown = float(drawdowns.min())
    calmar = cagr / abs(maximum_drawdown) if maximum_drawdown < 0 else float("inf")
    annual_returns = equity.resample("YE").last().pct_change().iloc[1:]
    if annual_returns.empty:
        annual_returns = pd.Series([total_return], dtype=float)
    return PerformanceMetrics(
        cagr=float(cagr),
        annualized_volatility=float(annualized_volatility),
        sharpe_ratio=sharpe,
        maximum_drawdown=maximum_drawdown,
        sortino_ratio=sortino,
        calmar_ratio=float(calmar),
        total_return=float(total_return),
        turnover=execution.turnover,
        total_transaction_costs=execution.total_transaction_costs,
        rebalances=execution.rebalances,
        time_in_market=execution.time_in_market,
        mean_cash_allocation=execution.mean_cash_allocation,
        maximum_cash_allocation=execution.maximum_cash_allocation,
        worst_calendar_year=float(annual_returns.min()),
        best_calendar_year=float(annual_returns.max()),
        longest_drawdown_days=_longest_drawdown_days(drawdowns),
    )


def compare_to_primary_benchmark(
    strategy_equity: pd.Series,
    benchmark_equity: pd.Series,
    strategy_metrics: PerformanceMetrics,
    benchmark_metrics: PerformanceMetrics,
    positive_excess_oos_fold_percentage: float,
) -> RelativeMetrics:
    """Compare aligned daily strategy and benchmark curves without selecting observations."""
    _validate_equity(strategy_equity)
    _validate_equity(benchmark_equity)
    if not strategy_equity.index.equals(benchmark_equity.index):
        raise ValueError("strategy and benchmark equity must share an identical daily index")
    if not 0.0 <= positive_excess_oos_fold_percentage <= 1.0:
        raise ValueError("positive-excess fold percentage must be in [0, 1]")
    active_returns = strategy_equity.pct_change().iloc[1:] - benchmark_equity.pct_change().iloc[1:]
    return RelativeMetrics(
        excess_cagr=strategy_metrics.cagr - benchmark_metrics.cagr,
        sharpe_difference=strategy_metrics.sharpe_ratio - benchmark_metrics.sharpe_ratio,
        maximum_drawdown_difference=(
            strategy_metrics.maximum_drawdown - benchmark_metrics.maximum_drawdown
        ),
        annualized_tracking_error=float(active_returns.std(ddof=0) * (TRADING_DAYS_PER_YEAR**0.5)),
        positive_excess_oos_fold_percentage=positive_excess_oos_fold_percentage,
    )


def classify_research_outcome(evidence: RobustnessEvidence) -> ResearchOutcome:
    """Apply the frozen protocol without using profitability as an engineering-pass proxy."""
    if not evidence.research_integrity_valid:
        return ResearchOutcome.INVALID_RESEARCH_RESULT
    required = (
        evidence.locked_test_net_cagr_exceeds_benchmark,
        evidence.locked_test_sharpe_exceeds_benchmark,
        evidence.locked_test_drawdown_not_worse,
        evidence.median_fold_excess_return_positive,
        evidence.positive_excess_fold_percentage_above_half,
        evidence.doubled_cost_excess_cagr_nonnegative,
        evidence.delayed_execution_excess_cagr_nonnegative,
        evidence.parameter_neighborhood_not_single_point_peak,
        evidence.not_driven_by_isolated_nonrepeatable_trades,
    )
    return (
        ResearchOutcome.ROBUST_OUTPERFORMANCE_OBSERVED
        if all(required)
        else ResearchOutcome.NO_EVIDENCE_OF_EDGE
    )


def _validate_equity(equity: pd.Series) -> None:
    """Reject non-daily, non-finite, non-positive curves before reporting metrics."""
    if (
        not isinstance(equity.index, pd.DatetimeIndex)
        or len(equity) < 2
        or not equity.index.is_monotonic_increasing
        or not equity.index.is_unique
        or equity.isna().any()
        or (equity <= 0).any()
    ):
        raise ValueError("equity must be a unique ascending, finite positive DatetimeIndex series")


def _annualized_ratio(returns: pd.Series, downside_only: bool) -> float:
    """Return a zero-risk-free annualized Sharpe or Sortino ratio."""
    denominator = returns[returns < 0].std(ddof=0) if downside_only else returns.std(ddof=0)
    if denominator == 0 or pd.isna(denominator):
        return float("inf") if returns.mean() > 0 else 0.0
    return float(returns.mean() / denominator * (TRADING_DAYS_PER_YEAR**0.5))


def _longest_drawdown_days(drawdowns: pd.Series) -> int:
    """Count the longest consecutive daily interval below the prior equity high-water mark."""
    longest = 0
    current = 0
    for value in drawdowns:
        if value < 0:
            current += 1
            longest = max(longest, current)
        else:
            current = 0
    return longest
