"""Frozen composition of point-in-time features and constrained portfolio construction."""

from __future__ import annotations

from decimal import Decimal

from quant_stack.features import FeatureRow
from quant_stack.portfolio import PortfolioConstraints, construct_weights


def etf_momentum_weights(rows: list[FeatureRow]) -> dict[str, Decimal]:
    """Return deterministic long-only weights from one same-date feature snapshot."""
    if not rows:
        return {"CASH": Decimal("1")}
    if len({row.bar.trading_date for row in rows}) != 1:
        raise ValueError("strategy requires one exchange-local feature date")
    return construct_weights(rows, PortfolioConstraints(Decimal("0.5"), Decimal("0.1"), 2))
