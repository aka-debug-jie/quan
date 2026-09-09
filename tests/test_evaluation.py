import pandas as pd
import pytest

from quant_stack.evaluation import (
    ExecutionStatistics,
    ResearchOutcome,
    RobustnessEvidence,
    classify_research_outcome,
    compare_to_primary_benchmark,
    evaluate_equity_curve,
)


def _execution() -> ExecutionStatistics:
    return ExecutionStatistics(0.4, 12.5, 3, 0.75, 0.25, 0.5)


def test_evaluation_reports_required_net_metrics() -> None:
    index = pd.to_datetime(["2024-01-02", "2024-01-03", "2024-01-04", "2024-01-05"])
    equity = pd.Series([100.0, 110.0, 99.0, 121.0], index=index)
    metrics = evaluate_equity_curve(equity, _execution())
    assert metrics.total_return == pytest.approx(0.21)
    assert metrics.maximum_drawdown == pytest.approx(-0.1)
    assert metrics.longest_drawdown_days == 1
    assert metrics.total_transaction_costs == 12.5


def test_primary_benchmark_comparison_requires_identical_observations() -> None:
    index = pd.date_range("2024-01-02", periods=4, freq="B")
    strategy = pd.Series([100.0, 110.0, 99.0, 121.0], index=index)
    benchmark = pd.Series([100.0, 105.0, 100.0, 110.0], index=index)
    relative = compare_to_primary_benchmark(
        strategy,
        benchmark,
        evaluate_equity_curve(strategy, _execution()),
        evaluate_equity_curve(benchmark, _execution()),
        0.5,
    )
    assert relative.excess_cagr > 0
    assert relative.positive_excess_oos_fold_percentage == 0.5
    with pytest.raises(ValueError, match="identical daily index"):
        compare_to_primary_benchmark(
            strategy,
            benchmark.iloc[1:],
            evaluate_equity_curve(strategy, _execution()),
            evaluate_equity_curve(benchmark, _execution()),
            0.5,
        )


def test_outcome_is_negative_when_any_robustness_condition_fails() -> None:
    robust = RobustnessEvidence(*(True for _ in range(10)))
    assert classify_research_outcome(robust) is ResearchOutcome.ROBUST_OUTPERFORMANCE_OBSERVED
    assert (
        classify_research_outcome(
            RobustnessEvidence(False, True, True, True, True, True, True, True, True, True)
        )
        is ResearchOutcome.NO_EVIDENCE_OF_EDGE
    )
    assert (
        classify_research_outcome(
            RobustnessEvidence(True, True, True, True, True, True, True, True, True, False)
        )
        is ResearchOutcome.INVALID_RESEARCH_RESULT
    )
