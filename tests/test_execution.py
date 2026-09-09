from decimal import Decimal

import pandas as pd
import pytest

from quant_stack.costs import CostModel
from quant_stack.execution import simulate_target_weights


def _costs() -> CostModel:
    return CostModel(Decimal("0.001"), Decimal("1"), Decimal("0"), Decimal("0"))


def test_close_signal_executes_only_on_later_open_with_costs() -> None:
    index = pd.date_range("2024-01-02", periods=3, freq="B")
    prices = pd.DataFrame({"ETF": [10.0, 11.0, 12.0]}, index=index)
    result = simulate_target_weights(
        prices,
        prices,
        {index[0]: {"ETF": Decimal("0.9"), "CASH": Decimal("0.1")}},
        _costs(),
    )
    assert result.rebalances == 1
    assert result.trades[0].execution_date == index[1]
    assert result.trades[0].transaction_cost > 0
    assert result.equity.iloc[0] == pytest.approx(100000.0)
    assert result.equity.iloc[1] < 100000.0


def test_last_session_signal_is_rejected_instead_of_filled_early() -> None:
    index = pd.date_range("2024-01-02", periods=2, freq="B")
    prices = pd.DataFrame({"ETF": [10.0, 11.0]}, index=index)
    result = simulate_target_weights(
        prices,
        prices,
        {index[-1]: {"ETF": Decimal("0.9"), "CASH": Decimal("0.1")}},
        _costs(),
    )
    assert result.rebalances == 0
    assert result.rejected_signal_dates == (index[-1],)
    assert result.equity.tolist() == [100000.0, 100000.0]


def test_target_must_be_long_only_and_fully_allocated() -> None:
    index = pd.date_range("2024-01-02", periods=2, freq="B")
    prices = pd.DataFrame({"ETF": [10.0, 11.0]}, index=index)
    with pytest.raises(ValueError, match="sum exactly"):
        simulate_target_weights(
            prices,
            prices,
            {index[0]: {"ETF": Decimal("0.8")}},
            _costs(),
        )
