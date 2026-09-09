"""Deterministic long-only portfolio construction from already-calculated feature rows."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from quant_stack.features import FeatureRow


@dataclass(frozen=True)
class PortfolioConstraints:
    """Long-only limits applied before any backtest or execution adapter exists."""

    max_asset_weight: Decimal
    minimum_cash_weight: Decimal
    max_positions: int


def construct_weights(
    rows: list[FeatureRow], constraints: PortfolioConstraints
) -> dict[str, Decimal]:
    """Filter trend-positive rows, rank momentum, inverse-vol weight, and retain required cash."""
    eligible = [
        row
        for row in rows
        if row.ma200 is not None
        and row.momentum_12m is not None
        and row.volatility_60d not in (None, Decimal("0"))
        and row.bar.close >= row.ma200
    ]
    selected = sorted(eligible, key=lambda row: (-_momentum(row), row.bar.symbol))[
        : constraints.max_positions
    ]
    if not selected:
        return {"CASH": Decimal("1")}
    inverse = {
        row.bar.symbol: Decimal("1") / row.volatility_60d
        for row in selected
        if row.volatility_60d is not None
    }
    budget = Decimal("1") - constraints.minimum_cash_weight
    total = sum(inverse.values(), Decimal("0"))
    weights = {
        symbol: min(budget * value / total, constraints.max_asset_weight)
        for symbol, value in inverse.items()
    }
    weights["CASH"] = Decimal("1") - sum(weights.values(), Decimal("0"))
    return weights


def _momentum(row: FeatureRow) -> Decimal:
    """Return the known momentum of an eligible feature row."""
    assert row.momentum_12m is not None
    return row.momentum_12m
