from decimal import Decimal

from quant_stack.features import FeatureRow
from quant_stack.models import DailyBar, Exchange, PriceBasis
from quant_stack.portfolio import PortfolioConstraints, construct_weights


def row(symbol: str, momentum: str, volatility: str) -> FeatureRow:
    bar = DailyBar(
        symbol=symbol,
        exchange=Exchange.SSE,
        price_basis=PriceBasis.CAUSAL_ADJUSTED,
        trading_date="2024-01-02",
        open=Decimal("10"),
        high=Decimal("10"),
        low=Decimal("10"),
        close=Decimal("10"),
        volume=Decimal("1"),
    )
    return FeatureRow(
        bar=bar,
        ma200=Decimal("9"),
        momentum_3m=Decimal(momentum),
        momentum_6m=Decimal(momentum),
        momentum_12m=Decimal(momentum),
        volatility_60d=Decimal(volatility),
    )


def test_portfolio_respects_cash_position_and_asset_caps() -> None:
    weights = construct_weights(
        [row("A", "2", "1"), row("B", "1", "2")],
        PortfolioConstraints(Decimal("0.4"), Decimal("0.2"), 2),
    )
    assert weights["A"] <= Decimal("0.4")
    assert weights["B"] <= Decimal("0.4")
    assert weights["CASH"] >= Decimal("0.2")
    assert sum(weights.values(), Decimal("0")) == Decimal("1")
