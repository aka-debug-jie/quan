from datetime import date
from decimal import Decimal

import pytest
from pydantic import ValidationError

from quant_stack.models import (
    BacktestConfig,
    DailyBar,
    Exchange,
    PriceBasis,
    Side,
    TargetPosition,
    assert_fill_after_signal,
    deterministic_order_id,
)


def test_daily_bar_rejects_illegal_ohlc() -> None:
    with pytest.raises(ValidationError, match="high must not be below"):
        DailyBar(
            symbol="SYNTH_A",
            exchange=Exchange.TEST,
            price_basis=PriceBasis.RAW,
            trading_date=date(2024, 1, 2),
            open=Decimal("10"),
            high=Decimal("9"),
            low=Decimal("8"),
            close=Decimal("10"),
            volume=Decimal("100"),
        )


def test_signal_cannot_fill_on_same_day() -> None:
    signal_date = date(2024, 1, 2)
    with pytest.raises(ValueError, match="later than signal_date"):
        assert_fill_after_signal(signal_date, signal_date)


def test_target_position_requires_later_effective_date() -> None:
    with pytest.raises(ValidationError, match="later than signal_date"):
        TargetPosition(
            symbol="SYNTH_A",
            signal_date=date(2024, 1, 2),
            effective_date=date(2024, 1, 2),
            target_weight=Decimal("0.5"),
        )


def test_order_id_is_idempotent() -> None:
    inputs = ("etf_momentum_v1", "SYNTH_A", Side.BUY, Decimal("100"), date(2024, 1, 2))
    assert deterministic_order_id(*inputs) == deterministic_order_id(*inputs)
    changed = deterministic_order_id(
        "etf_momentum_v1", "SYNTH_A", Side.BUY, Decimal("101"), date(2024, 1, 2)
    )
    assert changed != deterministic_order_id(*inputs)


def test_backtest_config_requires_all_cost_parameters() -> None:
    with pytest.raises(ValidationError, match="costs"):
        BacktestConfig.model_validate({"long_only": True, "leverage": 1})

    with pytest.raises(ValidationError, match="slippage_bps"):
        BacktestConfig.model_validate(
            {
                "costs": {
                    "commission_rate": "0.0003",
                    "minimum_commission": "5",
                    "half_spread_bps": "2",
                }
            }
        )
