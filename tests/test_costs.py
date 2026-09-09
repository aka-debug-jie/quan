from decimal import Decimal

from quant_stack.costs import CostModel, trade_cost


def test_cost_model_includes_minimum_commission_spread_slippage_and_stress() -> None:
    model = CostModel(Decimal("0.0003"), Decimal("5"), Decimal("0.0002"), Decimal("0.0001"))
    base = trade_cost(Decimal("1000"), model)
    assert base == Decimal("5.3000")
    assert trade_cost(Decimal("1000"), model, Decimal("2")) == Decimal("10.6000")
