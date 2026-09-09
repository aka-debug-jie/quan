"""Explicit transaction-cost model required before formal backtest reporting."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal


@dataclass(frozen=True)
class CostModel:
    """All mandatory long-only transaction cost parameters in decimal fractions."""

    commission_rate: Decimal
    minimum_commission: Decimal
    half_spread_rate: Decimal
    slippage_rate: Decimal


def trade_cost(notional: Decimal, model: CostModel, multiplier: Decimal = Decimal("1")) -> Decimal:
    """Return commission plus spread and slippage; multiplier supports prespecified stress tests."""
    if notional <= 0 or multiplier <= 0:
        raise ValueError("notional and cost multiplier must be positive")
    commission = max(notional * model.commission_rate, model.minimum_commission)
    return (commission + notional * (model.half_spread_rate + model.slippage_rate)) * multiplier
