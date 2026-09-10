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
    rows: list[FeatureRow], constraints: PortfolioConstraints, momentum_months: int = 12
) -> dict[str, Decimal]:
    """Filter trend-positive rows, rank momentum, inverse-vol weight, and retain required cash."""
    eligible = [
        row
        for row in rows
        if row.ma200 is not None
        and _momentum(row, momentum_months) is not None
        and row.volatility_60d not in (None, Decimal("0"))
        and row.bar.close >= row.ma200
    ]
    selected = sorted(
        eligible, key=lambda row: (-_required_momentum(row, momentum_months), row.bar.symbol)
    )[: constraints.max_positions]
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


def _momentum(row: FeatureRow, months: int) -> Decimal | None:
    """Return one preregistered momentum horizon without deriving a new feature."""
    if months == 3:
        return row.momentum_3m
    if months == 6:
        return row.momentum_6m
    if months == 12:
        return row.momentum_12m
    raise ValueError("momentum months must be one of 3, 6, or 12")


def _required_momentum(row: FeatureRow, months: int) -> Decimal:
    """Return the already-validated momentum value for one eligible row."""
    value = _momentum(row, months)
    assert value is not None
    return value
