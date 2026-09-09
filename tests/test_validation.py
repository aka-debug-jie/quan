from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest

from quant_stack.models import DailyBar, Exchange, PriceBasis
from quant_stack.validation import load_daily_bars_csv, reject_duplicate_bars

FIXTURE = Path(__file__).parent / "fixtures" / "synthetic_etf_daily.csv"


def test_synthetic_fixture_is_valid() -> None:
    bars = load_daily_bars_csv(FIXTURE)
    assert len(bars) == 6
    assert {bar.symbol for bar in bars} == {"SYNTH_A", "SYNTH_B"}


def test_duplicate_symbol_date_is_rejected() -> None:
    bar = DailyBar(
        symbol="SYNTH_A",
        exchange=Exchange.TEST,
        price_basis=PriceBasis.RAW,
        trading_date=date(2024, 1, 2),
        open=Decimal("10"),
        high=Decimal("11"),
        low=Decimal("9"),
        close=Decimal("10.5"),
        volume=Decimal("100"),
    )
    with pytest.raises(ValueError, match="duplicate bar"):
        reject_duplicate_bars([bar, bar])
