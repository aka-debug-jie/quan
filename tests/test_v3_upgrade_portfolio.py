"""Portfolio policy tests for the bounded research upgrade."""

from decimal import Decimal

import pandas as pd

from quant_stack_v3.upgrade_portfolio import (
    apply_weight_policy,
    policy_for,
    select_portfolio,
)


def _daily() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "symbol": [f"sh{600000 + index:06d}" for index in range(120)],
            "score_rank": range(1, 121),
            "liquidity_rank": range(1, 121),
        }
    )


def test_buffer_uses_actual_holdings_not_previous_target() -> None:
    policy = policy_for("AF7_TOP50_D20_HOLD100_BAND25")
    held = frozenset({"sh600070", "sh600110"})
    decision = select_portfolio(_daily(), held, policy)
    assert "sh600070" in decision.symbols
    assert "sh600110" not in decision.symbols
    assert "sh600070" in decision.retained


def test_low_score_avoidance_keeps_eighty_of_liquid_hundred() -> None:
    decision = select_portfolio(_daily(), frozenset(), policy_for("AF7_LOW_AVOID100_D20"))
    assert len(decision.symbols) == 80
    assert "sh600099" in decision.excluded_low_score
    assert "sh600100" not in decision.excluded_low_score


def test_weight_band_and_gradual_step_are_distinct() -> None:
    band = policy_for("AF7_TOP50_D20_HOLD100_BAND25")
    assert (
        apply_weight_policy(
            current_quantity=Decimal("100"),
            target_quantity=Decimal("120"),
            current_weight=Decimal("0.021"),
            target_weight=Decimal("0.02"),
            policy=band,
        )
        == 100
    )
    gradual = policy_for("AF7_TOP50_D5_STEP25")
    assert (
        apply_weight_policy(
            current_quantity=Decimal("100"),
            target_quantity=Decimal("200"),
            current_weight=Decimal("0.01"),
            target_weight=Decimal("0.02"),
            policy=gradual,
        )
        == 125
    )
