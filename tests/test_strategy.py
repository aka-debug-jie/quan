from datetime import date
from decimal import Decimal

import pandas as pd
import pytest

from quant_stack.features import FeatureRow
from quant_stack.models import DailyBar, Exchange, PriceBasis
from quant_stack.strategy import etf_momentum_weights, monthly_etf_momentum_targets


def row(day: str) -> FeatureRow:
    bar = DailyBar(
        symbol="A",
        exchange=Exchange.SSE,
        price_basis=PriceBasis.CAUSAL_ADJUSTED,
        trading_date=day,
        open=Decimal("10"),
        high=Decimal("10"),
        low=Decimal("10"),
        close=Decimal("10"),
        volume=Decimal("1"),
    )
    return FeatureRow(bar, Decimal("9"), Decimal("1"), Decimal("1"), Decimal("1"), Decimal("1"))


def test_strategy_rejects_mixed_feature_dates() -> None:
    with pytest.raises(ValueError, match="one exchange-local feature date"):
        etf_momentum_weights([row("2024-01-02"), row("2024-01-03")])


def test_monthly_targets_require_each_month_end_feature_snapshot() -> None:
    sessions = pd.to_datetime(["2024-01-30", "2024-01-31", "2024-02-01"])
    with pytest.raises(ValueError, match="feature snapshot"):
        monthly_etf_momentum_targets(sessions, {date(2024, 1, 31): [row("2024-01-31")]})
