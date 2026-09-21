"""Single-pass, append-only historical account for bounded V3 batch research."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from hashlib import sha256

from quant_stack.costs import CostModel
from quant_stack.data.models import CorporateActionEvent, CorporateActionKind
from quant_stack.models import Side
from quant_stack.paper_models import PaperExecutionRule
from quant_stack.research_json import canonical_json

GENESIS_HASH = "0" * 64


@dataclass(frozen=True)
class HistoricalOrder:
    """One close-derived order that expires on its exact execution session."""

    order_id: str
    symbol: str
    side: Side
    quantity: Decimal
    signal_date: date
    execution_date: date


@dataclass(frozen=True)
class HistoricalFill:
    """One raw-open simulated fill with explicit cost components."""

    order_id: str
    trading_date: date
    symbol: str
    side: Side
    quantity: Decimal
    raw_price: Decimal
    fill_price: Decimal
    notional: Decimal
    commission: Decimal
    spread_cost: Decimal
    slippage_cost: Decimal
    tax_cost: Decimal
    transfer_fee: Decimal


@dataclass(frozen=True)
class HistoricalRejection:
    """One expired order and its auditable reason."""

    order_id: str
    trading_date: date
    symbol: str
    reason: str


@dataclass(frozen=True)
class HistoricalSnapshot:
    """One end-of-session cash, position, receivable, and NAV state."""

    as_of_date: date
    cash: Decimal
    positions: dict[str, Decimal]
    net_asset_value: Decimal
    cumulative_fees: Decimal
    receivable_dividends: Decimal


@dataclass(frozen=True)
class Reconciliation:
    """Hash-chain head and final account state."""

    event_count: int
    head_hash: str
    snapshot: HistoricalSnapshot


class HistoricalAccount:
    """Maintain a deterministic in-memory account and immutable event hash chain."""

    def __init__(self, account_id: str, initial_cash: Decimal) -> None:
        if not account_id or initial_cash <= 0:
            raise ValueError("historical account requires id and positive cash")
        self.account_id = account_id
        self.cash = initial_cash
        self.positions: dict[str, Decimal] = {}
        self.receivable = Decimal("0")
        self.cumulative_fees = Decimal("0")
        self.orders: list[HistoricalOrder] = []
        self.fills: list[HistoricalFill] = []
        self.rejections: list[HistoricalRejection] = []
        self.snapshots: list[HistoricalSnapshot] = []
        self.events: list[dict[str, object]] = []
        self._entitlements: dict[str, tuple[date, Decimal]] = {}
        self._paid_entitlements: set[str] = set()
        self._append("initial_cash", None, {"cash": initial_cash})

    def place_order(self, order: HistoricalOrder) -> None:
        """Append one future-session order without any external transport."""
        if order.quantity <= 0 or order.execution_date <= order.signal_date:
            raise ValueError("historical order violates quantity or timing")
        self.orders.append(order)
        self._append("order", order.signal_date, order.__dict__)

    def transfer_position(
        self,
        transfer_id: str,
        effective_date: date,
        predecessor: str,
        successor: str,
        ratio: Decimal,
    ) -> None:
        """Apply one verified code/share conversion before the open."""
        quantity = self.positions.get(predecessor, Decimal("0"))
        if quantity <= 0:
            return
        if ratio <= 0 or predecessor == successor:
            raise ValueError("invalid historical position transfer")
        self.positions[predecessor] = Decimal("0")
        self.positions[successor] = self.positions.get(successor, Decimal("0")) + quantity * ratio
        self._append(
            "position_transfer",
            effective_date,
            {
                "transfer_id": transfer_id,
                "predecessor": predecessor,
                "successor": successor,
                "ratio": ratio,
                "quantity": quantity,
            },
        )

    def run_day(
        self,
        trading_date: date,
        raw_opens: dict[str, Decimal],
        raw_closes: dict[str, Decimal],
        costs: CostModel,
        actions: dict[str, tuple[CorporateActionEvent, ...]],
        blocks: dict[str, str],
        rules: dict[str, PaperExecutionRule],
    ) -> HistoricalSnapshot:
        """Apply pre-open actions, fills, close entitlements/payments, and raw-close NAV."""
        self._apply_splits(trading_date, actions)
        due = sorted(
            (item for item in self.orders if item.execution_date == trading_date),
            key=lambda item: (0 if item.side is Side.SELL else 1, item.order_id),
        )
        for order in due:
            self._fill_or_reject(order, trading_date, raw_opens, costs, blocks, rules)
        self._record_entitlements(trading_date, actions)
        self._pay_entitlements(trading_date)
        held = {symbol for symbol, quantity in self.positions.items() if quantity > 0}
        missing = held - set(raw_closes)
        if missing:
            raise ValueError(f"held positions lack valuation: {', '.join(sorted(missing))}")
        nav = (
            self.cash
            + self.receivable
            + sum(
                (
                    quantity * raw_closes[symbol]
                    for symbol, quantity in self.positions.items()
                    if quantity > 0
                ),
                Decimal("0"),
            )
        )
        snapshot = HistoricalSnapshot(
            trading_date,
            self.cash,
            dict(self.positions),
            nav,
            self.cumulative_fees,
            self.receivable,
        )
        self.snapshots.append(snapshot)
        self._append(
            "snapshot",
            trading_date,
            {
                "cash": self.cash,
                "positions": self.positions,
                "net_asset_value": nav,
                "cumulative_fees": self.cumulative_fees,
                "receivable_dividends": self.receivable,
                "raw_closes": {symbol: raw_closes[symbol] for symbol in sorted(held)},
            },
        )
        self._validate_state()
        return snapshot

    def reconcile(self) -> Reconciliation:
        """Verify the complete event hash chain and return its final state."""
        previous = GENESIS_HASH
        for sequence, event in enumerate(self.events, 1):
            if event["prev_hash"] != previous:
                raise ValueError(f"historical ledger prev hash differs at {sequence}")
            payload = str(event["payload"])
            expected = _event_hash(
                str(event["event_type"]),
                str(event["occurred_on"]),
                payload,
                previous,
            )
            if event["event_hash"] != expected:
                raise ValueError(f"historical ledger hash differs at {sequence}")
            previous = expected
        if not self.snapshots:
            raise ValueError("historical ledger has no snapshots")
        return Reconciliation(len(self.events), previous, self.snapshots[-1])

    def _fill_or_reject(
        self,
        order: HistoricalOrder,
        trading_date: date,
        raw_opens: dict[str, Decimal],
        costs: CostModel,
        blocks: dict[str, str],
        rules: dict[str, PaperExecutionRule],
    ) -> None:
        reason = blocks.get(order.symbol)
        if reason is not None:
            self._reject(order, trading_date, reason)
            return
        if order.symbol not in raw_opens:
            self._reject(order, trading_date, "missing_open_or_suspended")
            return
        raw_price = raw_opens[order.symbol]
        quantity = order.quantity
        if order.side is Side.SELL:
            if quantity > self.positions.get(order.symbol, Decimal("0")):
                raise ValueError("historical sell would create a short position")
        else:
            rule = rules[order.symbol]
            quantity = min(quantity, self._affordable_quantity(raw_price, costs, rule))
            if quantity <= 0:
                self._reject(order, trading_date, "insufficient_cash")
                return
        terms = _fill_terms(raw_price, quantity, order.side, costs)
        fill_price, notional, commission, spread, slippage, tax, transfer = terms
        if order.side is Side.BUY:
            self.cash -= notional + commission + transfer
            self.positions[order.symbol] = self.positions.get(order.symbol, Decimal("0")) + quantity
        else:
            self.cash += notional - commission - tax - transfer
            self.positions[order.symbol] = self.positions.get(order.symbol, Decimal("0")) - quantity
        self.cumulative_fees += commission + spread + slippage + tax + transfer
        fill = HistoricalFill(
            order.order_id,
            trading_date,
            order.symbol,
            order.side,
            quantity,
            raw_price,
            fill_price,
            notional,
            commission,
            spread,
            slippage,
            tax,
            transfer,
        )
        self.fills.append(fill)
        self._append("fill", trading_date, fill.__dict__)

    def _affordable_quantity(
        self, raw_price: Decimal, costs: CostModel, rule: PaperExecutionRule
    ) -> Decimal:
        if self.cash <= costs.minimum_commission:
            return Decimal("0")
        unit = raw_price * (Decimal("1") + costs.half_spread_rate + costs.slippage_rate)
        estimate = (self.cash - costs.minimum_commission) / (
            unit * (Decimal("1") + costs.transfer_fee_rate)
        )
        quantity = _lot_quantity(estimate, rule)
        while quantity > 0:
            _, notional, commission, _, _, _, transfer = _fill_terms(
                raw_price, quantity, Side.BUY, costs
            )
            if notional + commission + transfer <= self.cash:
                return quantity
            quantity -= rule.buy_increment
        return Decimal("0")

    def _reject(self, order: HistoricalOrder, trading_date: date, reason: str) -> None:
        rejection = HistoricalRejection(order.order_id, trading_date, order.symbol, reason)
        self.rejections.append(rejection)
        self._append("rejection", trading_date, rejection.__dict__)

    def _apply_splits(
        self, trading_date: date, actions: dict[str, tuple[CorporateActionEvent, ...]]
    ) -> None:
        for symbol, values in actions.items():
            for action in values:
                if (
                    action.kind is CorporateActionKind.SHARE_SPLIT
                    and action.effective_date == trading_date
                ):
                    quantity = self.positions.get(symbol, Decimal("0"))
                    if quantity <= 0:
                        continue
                    ratio = action.split_ratio or Decimal("0")
                    self.positions[symbol] = quantity * ratio
                    self._append(
                        "split",
                        trading_date,
                        {"symbol": symbol, "ratio": ratio},
                    )

    def _record_entitlements(
        self, trading_date: date, actions: dict[str, tuple[CorporateActionEvent, ...]]
    ) -> None:
        for symbol, values in actions.items():
            for action in values:
                if (
                    action.kind is CorporateActionKind.CASH_DISTRIBUTION
                    and action.record_date == trading_date
                ):
                    quantity = self.positions.get(symbol, Decimal("0"))
                    if quantity <= 0:
                        continue
                    if action.payment_date is None or action.cash_per_unit is None:
                        raise ValueError("held dividend lacks payment or cash value")
                    identity = sha256(
                        f"{symbol}:{action.effective_date}:{action.cash_per_unit}".encode()
                    ).hexdigest()
                    if identity in self._entitlements:
                        continue
                    cash = quantity * action.cash_per_unit
                    self._entitlements[identity] = (action.payment_date, cash)
                    self.receivable += cash
                    self._append(
                        "entitlement",
                        trading_date,
                        {
                            "identity": identity,
                            "symbol": symbol,
                            "quantity": quantity,
                            "cash_per_unit": action.cash_per_unit,
                            "payment_date": action.payment_date,
                        },
                    )

    def _pay_entitlements(self, trading_date: date) -> None:
        for identity, (payment_date, amount) in sorted(self._entitlements.items()):
            if identity in self._paid_entitlements or payment_date > trading_date:
                continue
            self.cash += amount
            self.receivable -= amount
            self._paid_entitlements.add(identity)
            self._append(
                "dividend_payment",
                trading_date,
                {"identity": identity, "cash": amount},
            )

    def _append(self, event_type: str, occurred_on: date | None, payload: object) -> None:
        payload_text = canonical_json(payload).decode("utf-8")
        previous = str(self.events[-1]["event_hash"]) if self.events else GENESIS_HASH
        date_text = occurred_on.isoformat() if occurred_on is not None else ""
        digest = _event_hash(event_type, date_text, payload_text, previous)
        self.events.append(
            {
                "sequence": len(self.events) + 1,
                "event_type": event_type,
                "occurred_on": date_text,
                "payload": payload_text,
                "prev_hash": previous,
                "event_hash": digest,
            }
        )

    def _validate_state(self) -> None:
        if (
            self.cash < 0
            or self.receivable < 0
            or any(quantity < 0 for quantity in self.positions.values())
        ):
            raise ValueError("historical account produced negative cash, receivable, or position")


def _fill_terms(
    raw_price: Decimal,
    quantity: Decimal,
    side: Side,
    costs: CostModel,
) -> tuple[Decimal, Decimal, Decimal, Decimal, Decimal, Decimal, Decimal]:
    rate = costs.half_spread_rate + costs.slippage_rate
    fill_price = raw_price * (Decimal("1") + rate if side is Side.BUY else Decimal("1") - rate)
    notional = fill_price * quantity
    commission = max(notional * costs.commission_rate, costs.minimum_commission)
    spread = raw_price * quantity * costs.half_spread_rate
    slippage = raw_price * quantity * costs.slippage_rate
    tax = notional * costs.sell_tax_rate if side is Side.SELL else Decimal("0")
    transfer = notional * costs.transfer_fee_rate
    return fill_price, notional, commission, spread, slippage, tax, transfer


def _lot_quantity(quantity: Decimal, rule: PaperExecutionRule) -> Decimal:
    if quantity < rule.minimum_buy_quantity:
        return Decimal("0")
    return (
        rule.minimum_buy_quantity
        + ((quantity - rule.minimum_buy_quantity) // rule.buy_increment) * rule.buy_increment
    )


def _event_hash(event_type: str, occurred_on: str, payload: str, previous: str) -> str:
    return sha256("|".join((event_type, occurred_on, payload, previous)).encode()).hexdigest()
