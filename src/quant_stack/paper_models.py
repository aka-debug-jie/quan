"""Typed, broker-free records used by the local paper ledger."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal

from quant_stack.costs import CostModel
from quant_stack.models import Side


@dataclass(frozen=True)
class PaperOrder:
    """A pre-created long-only order eligible on a later exchange date."""

    order_id: str
    symbol: str
    side: Side
    quantity: Decimal
    signal_date: date
    earliest_execution_date: date

    def __post_init__(self) -> None:
        """Enforce the close-signal timing and long-only quantity contract."""
        if not self.order_id or not self.symbol or self.quantity <= 0:
            raise ValueError("order_id, symbol, and positive quantity are required")
        if self.earliest_execution_date <= self.signal_date:
            raise ValueError("paper order execution must be after its signal date")


@dataclass(frozen=True)
class PaperFill:
    """One immutable raw-open paper fill and its individually visible costs."""

    fill_id: str
    order_id: str
    trading_date: date
    symbol: str
    side: Side
    quantity: Decimal
    raw_reference_price: Decimal
    fill_price: Decimal
    notional: Decimal
    commission: Decimal
    spread_cost: Decimal
    slippage_cost: Decimal
    manifest_id: str
    tax_cost: Decimal = Decimal("0")
    transfer_fee: Decimal = Decimal("0")


@dataclass(frozen=True)
class PaperExecutionRule:
    """Paper-only buy-size constraints for one exchange board."""

    minimum_buy_quantity: Decimal
    buy_increment: Decimal

    def __post_init__(self) -> None:
        """Require usable positive quantity constraints."""
        if self.minimum_buy_quantity <= 0 or self.buy_increment <= 0:
            raise ValueError("paper execution quantities must be positive")


@dataclass(frozen=True)
class PaperRejection:
    """An order not filled on a paper session, with an auditable reason."""

    order_id: str
    trading_date: date
    symbol: str
    reason: str


@dataclass(frozen=True)
class PaperSnapshot:
    """A reconstructed raw-close account state for one exchange-local date."""

    as_of_date: date
    cash: Decimal
    positions: Mapping[str, Decimal]
    net_asset_value: Decimal
    cumulative_fees: Decimal
    run_id: str
    receivable_dividends: Decimal = Decimal("0")
    generated_at: datetime | None = None
    is_backfill: bool = False


@dataclass(frozen=True)
class ReconciliationResult:
    """Successful replay result; an exception is raised for an invalid ledger."""

    event_count: int
    head_hash: str
    snapshot: PaperSnapshot


@dataclass(frozen=True)
class PaperBrokerConfig:
    """Frozen account parameters; no live-broker settings are accepted."""

    account_id: str
    costs: CostModel
    initial_cash: Decimal = Decimal("100000")

    def __post_init__(self) -> None:
        """Reject non-positive capital or anonymous account stores."""
        if not self.account_id or self.initial_cash <= 0:
            raise ValueError("account_id and positive initial_cash are required")
