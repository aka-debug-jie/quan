"""Cross-module no-lookahead regression checks for the research pipeline."""

from datetime import date
from decimal import Decimal

import pandas as pd
import pytest

from quant_stack.backtest import run_t1_backtest
from quant_stack.features import calculate_features
from quant_stack.models import DailyBar, Exchange, PriceBasis


def test_t1_adapter_rejects_misaligned_signal_index() -> None:
    close = pd.Series([1.0], index=pd.DatetimeIndex(["2024-01-02"]))
    signal = pd.Series([True], index=pd.DatetimeIndex(["2024-01-03"]))
    with pytest.raises(ValueError, match="identical index"):
        run_t1_backtest(close, signal)


def test_feature_order_rejects_out_of_order_observations() -> None:
    later = DailyBar(
        symbol="X",
        exchange=Exchange.SSE,
        price_basis=PriceBasis.CAUSAL_ADJUSTED,
        trading_date=date(2024, 1, 3),
        open=Decimal("1"),
        high=Decimal("1"),
        low=Decimal("1"),
        close=Decimal("1"),
        volume=Decimal("1"),
    )
    earlier = later.model_copy(update={"trading_date": date(2024, 1, 2)})
    with pytest.raises(ValueError, match="ascending"):
        calculate_features([later, earlier])
