"""Frozen cost-scenario semantics."""

from datetime import date
from decimal import Decimal
from pathlib import Path

from quant_stack_v3.protocol import load_protocol
from quant_stack_v3.upgrade_runner import _costs

ROOT = Path(__file__).parents[1]


def test_zero_and_double_cost_scenarios_keep_statutory_boundary_explicit() -> None:
    protocol = load_protocol(ROOT / "configs/v3/cn_historical_research_v3.yaml")
    session = date(2024, 1, 2)
    real = _costs(protocol, session, "real")
    doubled = _costs(protocol, session, "double_assumption")
    zero = _costs(protocol, session, "zero_all")
    assert doubled.commission_rate == real.commission_rate * 2
    assert doubled.minimum_commission == real.minimum_commission * 2
    assert doubled.half_spread_rate == real.half_spread_rate * 2
    assert doubled.slippage_rate == real.slippage_rate * 2
    assert doubled.sell_tax_rate == real.sell_tax_rate
    assert doubled.transfer_fee_rate == real.transfer_fee_rate
    assert zero == type(zero)(*(Decimal("0") for _ in range(6)))
