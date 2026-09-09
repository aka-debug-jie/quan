"""Pure point-in-time ETF feature calculations independent of strategies and execution."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from quant_stack.models import DailyBar


@dataclass(frozen=True)
class FeatureRow:
    """Features known only after one exchange-local daily close."""

    bar: DailyBar
    ma200: Decimal | None
    momentum_3m: Decimal | None
    momentum_6m: Decimal | None
    momentum_12m: Decimal | None
    volatility_60d: Decimal | None


def calculate_features(bars: list[DailyBar]) -> list[FeatureRow]:
    """Calculate trailing features with explicit warm-up nulls and no filling or future access."""
    if not bars:
        return []
    ordered = sorted(bars, key=lambda item: item.trading_date)
    if ordered != bars or len({bar.trading_date for bar in bars}) != len(bars):
        raise ValueError("feature bars must be unique and ascending")
    if any(bar.symbol != bars[0].symbol or bar.exchange is not bars[0].exchange for bar in bars):
        raise ValueError("feature bars must contain one instrument")
    rows: list[FeatureRow] = []
    closes = [bar.close for bar in bars]
    for index, bar in enumerate(bars):
        rows.append(
            FeatureRow(
                bar=bar,
                ma200=_mean(closes[index - 199 : index + 1]) if index >= 199 else None,
                momentum_3m=_return(closes, index, 63),
                momentum_6m=_return(closes, index, 126),
                momentum_12m=_return(closes, index, 252),
                volatility_60d=_volatility(closes, index),
            )
        )
    return rows


def _return(closes: list[Decimal], index: int, window: int) -> Decimal | None:
    """Return close-to-close momentum only after the full lookback exists."""
    if index < window:
        return None
    return closes[index] / closes[index - window] - Decimal("1")


def _volatility(closes: list[Decimal], index: int) -> Decimal | None:
    """Return population standard deviation of the 60 trailing close returns."""
    if index < 60:
        return None
    returns = [
        closes[position] / closes[position - 1] - Decimal("1")
        for position in range(index - 59, index + 1)
    ]
    mean = _mean(returns)
    return (_mean([(value - mean) ** 2 for value in returns])).sqrt()


def _mean(values: list[Decimal]) -> Decimal:
    """Return an exact Decimal arithmetic mean for a non-empty finite window."""
    return sum(values, Decimal("0")) / Decimal(len(values))
