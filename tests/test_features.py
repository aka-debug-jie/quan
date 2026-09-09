from datetime import date, timedelta
from decimal import Decimal

from quant_stack.features import calculate_features
from quant_stack.models import DailyBar, Exchange, PriceBasis


def bars(count: int) -> list[DailyBar]:
    return [
        DailyBar(
            symbol="510300",
            exchange=Exchange.SSE,
            price_basis=PriceBasis.CAUSAL_ADJUSTED,
            trading_date=date(2020, 1, 1) + timedelta(days=index),
            open=Decimal(index + 1),
            high=Decimal(index + 1),
            low=Decimal(index + 1),
            close=Decimal(index + 1),
            volume=Decimal("1"),
        )
        for index in range(count)
    ]


def test_features_have_explicit_warmup_and_do_not_use_future_bars() -> None:
    rows = calculate_features(bars(253))
    assert rows[198].ma200 is None
    assert rows[199].ma200 == Decimal("100.5")
    assert rows[62].momentum_3m is None
    assert rows[63].momentum_3m == Decimal("63")
    assert rows[251].momentum_12m is None
    assert rows[252].momentum_12m == Decimal("252")
    assert rows[60].volatility_60d is not None
