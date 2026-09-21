"""Offline comparison rules for the bounded independent-source sample."""

from __future__ import annotations

import pandas as pd

from quant_stack_v3.crosscheck import _compare


def test_crosscheck_uses_tick_and_relative_amount_tolerances() -> None:
    local = pd.Series(
        {
            "raw_open": 10.0,
            "raw_high": 10.2,
            "raw_low": 9.8,
            "raw_close": 10.1,
            "raw_volume": 1_000_000,
            "amount": 10_000_000,
            "st": False,
            "suspended": False,
        }
    )
    provider = pd.Series(
        {
            "open": "10.00",
            "high": "10.20",
            "low": "9.80",
            "close": "10.10",
            "volume": "1000100",
            "amount": "10000500",
            "tradestatus": "1",
            "isST": "0",
        }
    )
    assert _compare(local, provider) == []
    provider["close"] = "10.12"
    assert _compare(local, provider) == ["raw_close"]
