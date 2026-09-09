"""Typed domain models and timing invariants for M0."""

from __future__ import annotations

from datetime import UTC, date, datetime
from decimal import Decimal
from enum import StrEnum
from typing import Annotated, Literal
from uuid import NAMESPACE_URL, uuid5

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

PositiveDecimal = Annotated[Decimal, Field(gt=0)]
NonNegativeDecimal = Annotated[Decimal, Field(ge=0)]
Weight = Annotated[Decimal, Field(ge=0, le=1)]


class DomainModel(BaseModel):
    """Immutable base class for versioned research records."""

    model_config = ConfigDict(extra="forbid", frozen=True)


class AssetClass(StrEnum):
    """Asset classes supported by the M0 domain vocabulary."""

    ETF = "etf"


class Exchange(StrEnum):
    """Trading venues supported by the M0 and data-foundation contracts."""

    SSE = "SSE"
    SZSE = "SZSE"
    TEST = "TEST"


class PriceBasis(StrEnum):
    """Provider price transformations retained as independent time series."""

    RAW = "raw"
    QFQ = "qfq"


class Side(StrEnum):
    """Paper-order direction; V1 is long-only, so SELL only reduces holdings."""

    BUY = "buy"
    SELL = "sell"


class Instrument(DomainModel):
    """Exchange-listed instrument identified independently of a data provider."""

    symbol: Annotated[str, Field(min_length=1)]
    exchange: Exchange
    currency: Annotated[str, Field(min_length=3, max_length=3)] = "CNY"
    asset_class: Literal[AssetClass.ETF] = AssetClass.ETF


class DailyBar(DomainModel):
    """One exchange-local daily OHLCV observation."""

    symbol: Annotated[str, Field(min_length=1)]
    exchange: Exchange
    price_basis: PriceBasis
    trading_date: date
    open: PositiveDecimal
    high: PositiveDecimal
    low: PositiveDecimal
    close: PositiveDecimal
    volume: NonNegativeDecimal

    @model_validator(mode="after")
    def validate_ohlc(self) -> DailyBar:
        """Reject bars whose high/low cannot contain open and close."""
        if self.low > min(self.open, self.close):
            raise ValueError("low must not exceed open or close")
        if self.high < max(self.open, self.close):
            raise ValueError("high must not be below open or close")
        if self.low > self.high:
            raise ValueError("low must not exceed high")
        return self


class Signal(DomainModel):
    """Strategy output calculated after an exchange-local trading date closes."""

    strategy_id: Annotated[str, Field(min_length=1)]
    symbol: Annotated[str, Field(min_length=1)]
    signal_date: date
    generated_at: datetime
    score: Decimal

    @field_validator("generated_at")
    @classmethod
    def generated_at_must_be_timezone_aware(cls, value: datetime) -> datetime:
        """Require an unambiguous timestamp and normalize it to UTC."""
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("generated_at must be timezone-aware")
        return value.astimezone(UTC)


class TargetPosition(DomainModel):
    """Long-only desired portfolio weight effective on a later trading date."""

    symbol: Annotated[str, Field(min_length=1)]
    signal_date: date
    effective_date: date
    target_weight: Weight

    @model_validator(mode="after")
    def effective_after_signal(self) -> TargetPosition:
        """Prevent a close-derived target from becoming effective on day T."""
        if self.effective_date <= self.signal_date:
            raise ValueError("effective_date must be later than signal_date")
        return self


class OrderIntent(DomainModel):
    """Idempotent paper-order instruction; it cannot submit a broker order."""

    order_id: Annotated[str, Field(min_length=1)]
    strategy_id: Annotated[str, Field(min_length=1)]
    symbol: Annotated[str, Field(min_length=1)]
    side: Side
    quantity: PositiveDecimal
    signal_date: date
    earliest_execution_date: date

    @model_validator(mode="after")
    def execution_after_signal(self) -> OrderIntent:
        """Enforce the T-close to T+1-or-later execution boundary."""
        if self.earliest_execution_date <= self.signal_date:
            raise ValueError("earliest_execution_date must be later than signal_date")
        return self


class SimulatedFill(DomainModel):
    """A paper fill recorded without contacting a broker."""

    fill_id: Annotated[str, Field(min_length=1)]
    order_id: Annotated[str, Field(min_length=1)]
    trading_date: date
    price: PositiveDecimal
    quantity: PositiveDecimal
    commission: NonNegativeDecimal
    spread_cost: NonNegativeDecimal
    slippage_cost: NonNegativeDecimal


class PortfolioSnapshot(DomainModel):
    """End-of-day paper portfolio state."""

    as_of_date: date
    cash: NonNegativeDecimal
    positions: dict[str, NonNegativeDecimal]
    net_asset_value: NonNegativeDecimal


class ManifestFile(DomainModel):
    """One content-addressed file in a raw-data snapshot."""

    relative_path: Annotated[str, Field(min_length=1)]
    sha256: Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]
    size_bytes: Annotated[int, Field(ge=0)]


class DataManifest(DomainModel):
    """Identity and provenance for an immutable data snapshot."""

    snapshot_id: Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]
    source: Annotated[str, Field(min_length=1)]
    created_at: datetime
    files: tuple[ManifestFile, ...]

    @field_validator("created_at")
    @classmethod
    def created_at_must_be_timezone_aware(cls, value: datetime) -> datetime:
        """Require an unambiguous creation timestamp and normalize it to UTC."""
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("created_at must be timezone-aware")
        return value.astimezone(UTC)


class CostModel(DomainModel):
    """Required explicit costs for any future backtest implementation."""

    commission_rate: NonNegativeDecimal
    minimum_commission: NonNegativeDecimal
    half_spread_bps: NonNegativeDecimal
    slippage_bps: NonNegativeDecimal


class BacktestConfig(DomainModel):
    """Minimal V1 backtest configuration with mandatory safety boundaries."""

    costs: CostModel
    long_only: Literal[True] = True
    leverage: Literal[1] = 1


def deterministic_order_id(
    strategy_id: str,
    symbol: str,
    side: Side,
    quantity: Decimal,
    signal_date: date,
) -> str:
    """Create a stable ID so rerunning one intended order is idempotent."""
    identity = "|".join(
        (strategy_id, symbol, side.value, str(quantity.normalize()), signal_date.isoformat())
    )
    return str(uuid5(NAMESPACE_URL, f"quant-stack/order/{identity}"))


def assert_fill_after_signal(signal_date: date, fill_date: date) -> None:
    """Reject same-day or earlier simulated execution for a close-derived signal."""
    if fill_date <= signal_date:
        raise ValueError("fill_date must be later than signal_date")
