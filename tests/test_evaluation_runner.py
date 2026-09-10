from datetime import date
from decimal import Decimal

import pandas as pd

from quant_stack.costs import CostModel
from quant_stack.evaluation_runner import evaluate_walk_forward
from quant_stack.walk_forward import WalkForwardSplit


def test_walk_forward_retains_each_oos_fold_and_uses_equal_weight_primary_benchmark() -> None:
    index = pd.to_datetime(
        [
            "2024-01-29",
            "2024-01-30",
            "2024-01-31",
            "2024-02-01",
            "2024-02-02",
            "2024-02-26",
            "2024-02-27",
            "2024-02-28",
            "2024-02-29",
            "2024-03-01",
        ]
    )
    prices = pd.DataFrame({"A": range(10, 20), "B": range(20, 30)}, index=index, dtype=float)
    raw_open = prices * 2
    targets = {
        index[2]: {"A": Decimal("0.9"), "B": Decimal("0"), "CASH": Decimal("0.1")},
        index[8]: {"A": Decimal("0"), "B": Decimal("0.9"), "CASH": Decimal("0.1")},
    }
    folds = evaluate_walk_forward(
        prices,
        prices,
        targets,
        (
            WalkForwardSplit(
                date(2024, 1, 29), date(2024, 1, 30), date(2024, 1, 31), date(2024, 2, 2)
            ),
            WalkForwardSplit(
                date(2024, 2, 26), date(2024, 2, 28), date(2024, 2, 29), date(2024, 3, 1)
            ),
        ),
        CostModel(Decimal("0"), Decimal("0"), Decimal("0"), Decimal("0")),
        execution_audit_prices=raw_open,
    )
    assert len(folds) == 2
    assert folds[0].strategy.equity.index[0] == pd.Timestamp("2024-01-31")
    assert folds[0].benchmark.rebalances == 1
    assert folds[0].strategy.trades[0].raw_fill_price == Decimal("26.0")
    assert all(fold.relative_metrics.positive_excess_oos_fold_percentage == 0.5 for fold in folds)


def test_three_asset_benchmark_weights_remain_exactly_normalized() -> None:
    from quant_stack.benchmarks import same_universe_equal_weight_targets

    session = pd.Timestamp("2024-01-31")
    target = same_universe_equal_weight_targets((session,), ("A", "B", "C"))[session]

    assert sum(target.values(), Decimal("0")) == Decimal("1")
    assert target["CASH"] >= 0
