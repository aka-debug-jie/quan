import pandas as pd

from quant_stack.backtest import run_t1_backtest


def test_close_signal_cannot_enter_at_same_close() -> None:
    index = pd.date_range("2024-01-02", periods=3, freq="B")
    portfolio = run_t1_backtest(
        pd.Series([10.0, 11.0, 12.0], index=index), pd.Series([True, False, False], index=index)
    )
    records = portfolio.orders.records_readable
    assert records.iloc[0]["Timestamp"] == index[1]
