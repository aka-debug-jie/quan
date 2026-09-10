"""SQLite-backed, append-only paper broker.  It cannot submit live orders."""

from __future__ import annotations

import hashlib
import json
import sqlite3
from collections.abc import Iterable, Mapping
from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import Any
from uuid import NAMESPACE_URL, uuid5

from quant_stack.data.models import CorporateActionEvent, CorporateActionKind
from quant_stack.models import Side
from quant_stack.paper_models import (
    PaperBrokerConfig,
    PaperFill,
    PaperOrder,
    PaperRejection,
    PaperSnapshot,
    ReconciliationResult,
)

_GENESIS_HASH = "0" * 64


class PaperLedgerError(ValueError):
    """Raised when immutable ledger evidence or account invariants are invalid."""


class PaperBroker:
    """Maintain a local WAL paper account using exact Decimal string accounting."""

    def __init__(self, database_path: Path, config: PaperBrokerConfig) -> None:
        """Open (but do not initialize) a ledger database at ``database_path``."""
        self.database_path = database_path
        self.config = config

    def initialize(self) -> PaperSnapshot:
        """Create the schema and the single initial CNY cash-credit event idempotently."""
        with self._connection() as connection:
            self._create_schema(connection)
            row = connection.execute(
                "SELECT value FROM metadata WHERE key = 'account_id'"
            ).fetchone()
            if row is not None and row[0] != self.config.account_id:
                raise PaperLedgerError("database already belongs to a different account")
            connection.execute(
                "INSERT OR IGNORE INTO metadata(key, value) VALUES ('account_id', ?)",
                (self.config.account_id,),
            )
            event_id = self._stable_id("initial-cash")
            self._append_event(
                connection,
                event_id,
                "initial_cash",
                None,
                {"cash": _text(self.config.initial_cash), "currency": "CNY"},
            )
            return self._rebuild(connection)

    def place_order(self, order: PaperOrder) -> PaperOrder:
        """Append one idempotent, T+1-or-later paper order without a broker call."""
        with self._connection() as connection:
            self._require_initialized(connection)
            self._append_event(
                connection,
                order.order_id,
                "order",
                order.signal_date,
                {
                    "symbol": order.symbol,
                    "side": order.side.value,
                    "quantity": _text(order.quantity),
                    "signal_date": order.signal_date.isoformat(),
                    "earliest_execution_date": order.earliest_execution_date.isoformat(),
                },
            )
        return order

    def run_daily(
        self,
        run_id: str,
        trading_date: date,
        raw_opens: Mapping[str, Decimal],
        raw_closes: Mapping[str, Decimal],
        manifest_id: str,
        corporate_actions: Mapping[str, Iterable[CorporateActionEvent]]
        | Iterable[CorporateActionEvent] = (),
    ) -> PaperSnapshot:
        """Apply actions, fill eligible orders at raw opens, and write raw-close NAV once."""
        if not run_id or not manifest_id:
            raise ValueError("run_id and manifest_id are required")
        self._validate_prices(raw_opens, raw_closes)
        actions: Mapping[str, Iterable[CorporateActionEvent]] | tuple[CorporateActionEvent, ...]
        actions = (
            corporate_actions
            if isinstance(corporate_actions, Mapping)
            else tuple(corporate_actions)
        )
        with self._connection() as connection:
            self._require_initialized(connection)
            existing = connection.execute(
                "SELECT snapshot_json FROM runs WHERE run_id = ? AND status = 'complete'", (run_id,)
            ).fetchone()
            if existing is not None:
                return _snapshot_from_payload(json.loads(existing[0]))
            other = connection.execute(
                "SELECT run_id FROM runs WHERE trading_date = ? AND status = 'complete'",
                (trading_date.isoformat(),),
            ).fetchone()
            if other is not None:
                raise PaperLedgerError("trading date already completed by another run")
            connection.execute(
                "INSERT OR IGNORE INTO runs(run_id, trading_date, status, snapshot_json) "
                "VALUES (?, ?, 'running', NULL)",
                (run_id, trading_date.isoformat()),
            )
            state = self._rebuild(connection)
            self._apply_actions(connection, trading_date, actions, state.positions)
            state = self._rebuild(connection)
            self._fill_orders(connection, trading_date, raw_opens, manifest_id, state)
            state = self._rebuild(connection)
            snapshot = self._append_snapshot(
                connection, run_id, trading_date, raw_closes, manifest_id, state
            )
            encoded = json.dumps(_snapshot_payload(snapshot), sort_keys=True, separators=(",", ":"))
            connection.execute(
                "UPDATE runs SET status = 'complete', snapshot_json = ? WHERE run_id = ?",
                (encoded, run_id),
            )
            return snapshot

    def snapshot(self) -> PaperSnapshot:
        """Rebuild and return account state without trusting cached projections."""
        with self._connection() as connection:
            self._require_initialized(connection)
            return self._rebuild(connection)

    def fills(self) -> tuple[PaperFill, ...]:
        """Return fills reconstructed from immutable events in append order."""
        with self._connection() as connection:
            self._require_initialized(connection)
            return tuple(
                _fill_from_payload(json.loads(row[0]))
                for row in connection.execute(
                    "SELECT payload FROM events WHERE event_type = 'fill' ORDER BY sequence"
                )
            )

    def snapshots(self) -> tuple[PaperSnapshot, ...]:
        """Return every immutable daily raw-close snapshot in chronological ledger order."""
        with self._connection() as connection:
            self._require_initialized(connection)
            return tuple(
                _snapshot_from_payload(json.loads(row[0]))
                for row in connection.execute(
                    "SELECT payload FROM events WHERE event_type = 'snapshot' ORDER BY sequence"
                )
            )

    def orders(self) -> tuple[PaperOrder, ...]:
        """Return every immutable paper order in append order for operational reporting."""
        with self._connection() as connection:
            self._require_initialized(connection)
            return tuple(
                _order_from_payload(str(row[0]), json.loads(row[1]))
                for row in connection.execute(
                    "SELECT event_id, payload FROM events "
                    "WHERE event_type = 'order' ORDER BY sequence"
                )
            )

    def rejections(self) -> tuple[PaperRejection, ...]:
        """Return rejected paper orders without treating them as fills."""
        with self._connection() as connection:
            self._require_initialized(connection)
            return tuple(
                PaperRejection(
                    str(payload["order_id"]),
                    date.fromisoformat(str(payload["trading_date"])),
                    str(payload["symbol"]),
                    str(payload["reason"]),
                )
                for row in connection.execute(
                    "SELECT payload FROM events "
                    "WHERE event_type = 'rejected_order' ORDER BY sequence"
                )
                for payload in (json.loads(row[0]),)
            )

    def reconcile(self) -> ReconciliationResult:
        """Verify hashes and accounting invariants, then replay the complete ledger."""
        with self._connection() as connection:
            self._require_initialized(connection)
            snapshot = self._rebuild(connection)
            row = connection.execute(
                "SELECT COUNT(*), COALESCE(MAX(event_hash), ?) FROM events", (_GENESIS_HASH,)
            ).fetchone()
            assert row is not None
            return ReconciliationResult(int(row[0]), str(row[1]), snapshot)

    def _connection(self) -> sqlite3.Connection:
        self.database_path.parent.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(self.database_path)
        connection.execute("PRAGMA journal_mode=WAL")
        connection.execute("PRAGMA foreign_keys=ON")
        return connection

    def _create_schema(self, connection: sqlite3.Connection) -> None:
        connection.executescript(
            """
            CREATE TABLE IF NOT EXISTS metadata (key TEXT PRIMARY KEY, value TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS events (
              sequence INTEGER PRIMARY KEY AUTOINCREMENT, event_id TEXT NOT NULL UNIQUE,
              event_type TEXT NOT NULL, occurred_on TEXT, payload TEXT NOT NULL,
              prev_hash TEXT NOT NULL, event_hash TEXT NOT NULL UNIQUE
            );
            CREATE TABLE IF NOT EXISTS runs (
              run_id TEXT PRIMARY KEY, trading_date TEXT NOT NULL UNIQUE, status TEXT NOT NULL,
              snapshot_json TEXT
            );
            """
        )

    def _require_initialized(self, connection: sqlite3.Connection) -> None:
        self._create_schema(connection)
        if connection.execute("SELECT 1 FROM metadata WHERE key = 'account_id'").fetchone() is None:
            raise PaperLedgerError("paper account has not been initialized")

    def _append_event(
        self,
        connection: sqlite3.Connection,
        event_id: str,
        event_type: str,
        occurred_on: date | None,
        payload: Mapping[str, Any],
    ) -> None:
        encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"))
        existing = connection.execute(
            "SELECT event_type, payload FROM events WHERE event_id = ?", (event_id,)
        ).fetchone()
        if existing is not None:
            if existing[0] != event_type or existing[1] != encoded:
                raise PaperLedgerError("idempotency key conflicts with existing event")
            return
        previous = connection.execute(
            "SELECT event_hash FROM events ORDER BY sequence DESC LIMIT 1"
        ).fetchone()
        prev_hash = _GENESIS_HASH if previous is None else str(previous[0])
        date_text = None if occurred_on is None else occurred_on.isoformat()
        digest = _event_hash(event_id, event_type, date_text, encoded, prev_hash)
        connection.execute(
            "INSERT INTO events(event_id,event_type,occurred_on,payload,prev_hash,event_hash) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (event_id, event_type, date_text, encoded, prev_hash, digest),
        )

    def _apply_actions(
        self,
        connection: sqlite3.Connection,
        trading_date: date,
        actions: Mapping[str, Iterable[CorporateActionEvent]] | tuple[CorporateActionEvent, ...],
        positions: Mapping[str, Decimal],
    ) -> None:
        if isinstance(actions, Mapping):
            action_pairs = tuple(
                (symbol, action) for symbol, listed in actions.items() for action in listed
            )
        elif len(positions) == 1:
            action_pairs = tuple((next(iter(positions)), action) for action in actions)
        elif actions:
            raise PaperLedgerError("corporate actions require an explicit symbol mapping")
        else:
            action_pairs = ()
        for symbol, action in action_pairs:
            action_id = self._action_id(action)
            if (
                action.kind is CorporateActionKind.SHARE_SPLIT
                and action.effective_date == trading_date
            ):
                self._append_event(
                    connection,
                    f"{action_id}:split:{symbol}",
                    "split",
                    trading_date,
                    {
                        "symbol": symbol,
                        "ratio": _text(action.split_ratio or Decimal("0")),
                    },
                )
            if action.kind is CorporateActionKind.CASH_DISTRIBUTION:
                record_date = action.record_date or action.effective_date
                if record_date == trading_date:
                    quantity = positions.get(symbol, Decimal("0"))
                    if quantity > 0:
                        if action.payment_date is None:
                            raise PaperLedgerError(
                                "cash distribution for held position lacks payment_date"
                            )
                        self._append_event(
                            connection,
                            f"{action_id}:entitlement:{symbol}",
                            "entitlement",
                            trading_date,
                            {
                                "symbol": symbol,
                                "quantity": _text(quantity),
                                "cash_per_unit": _text(action.cash_per_unit or Decimal("0")),
                                "payment_date": action.payment_date.isoformat(),
                            },
                        )
                if action.payment_date == trading_date:
                    for row in connection.execute(
                        "SELECT event_id, payload FROM events WHERE event_type = 'entitlement'"
                    ):
                        entitlement = json.loads(row[1])
                        if entitlement["payment_date"] == trading_date.isoformat():
                            self._append_event(
                                connection,
                                f"{row[0]}:payment",
                                "dividend_payment",
                                trading_date,
                                {
                                    "symbol": entitlement["symbol"],
                                    "cash": _text(
                                        Decimal(entitlement["quantity"])
                                        * Decimal(entitlement["cash_per_unit"])
                                    ),
                                },
                            )

    def _fill_orders(
        self,
        connection: sqlite3.Connection,
        trading_date: date,
        raw_opens: Mapping[str, Decimal],
        manifest_id: str,
        state: PaperSnapshot,
    ) -> None:
        orders = connection.execute(
            "SELECT event_id, payload FROM events WHERE event_type = 'order' ORDER BY sequence"
        ).fetchall()
        positions = dict(state.positions)
        cash = state.cash
        for order_id, payload_text in orders:
            if connection.execute(
                "SELECT 1 FROM events WHERE event_type = 'fill' AND payload LIKE ?",
                (f'%"order_id":"{order_id}"%',),
            ).fetchone():
                continue
            payload = json.loads(payload_text)
            if date.fromisoformat(payload["earliest_execution_date"]) > trading_date:
                continue
            symbol = payload["symbol"]
            if symbol not in raw_opens:
                raise PaperLedgerError(f"raw open missing for {symbol}")
            side = Side(payload["side"])
            requested = Decimal(payload["quantity"])
            if side is Side.SELL and requested > positions.get(symbol, Decimal("0")):
                raise PaperLedgerError("paper sell would create a short position")
            raw_price = raw_opens[symbol]
            fill_price, commission, spread, slippage = self._fill_terms(raw_price, requested, side)
            notional = fill_price * requested
            if side is Side.BUY:
                affordable = self._affordable_quantity(cash, raw_price)
                quantity = min(requested, affordable)
                if quantity <= 0:
                    self._append_event(
                        connection,
                        self._stable_id(f"reject:{order_id}:{trading_date.isoformat()}"),
                        "rejected_order",
                        trading_date,
                        {
                            "order_id": str(order_id),
                            "trading_date": trading_date.isoformat(),
                            "symbol": symbol,
                            "reason": "insufficient_cash",
                        },
                    )
                    continue
                fill_price, commission, spread, slippage = self._fill_terms(
                    raw_price, quantity, side
                )
                notional = fill_price * quantity
                if notional + commission > cash:
                    quantity = quantity.next_minus()
                    if quantity <= 0:
                        continue
                    fill_price, commission, spread, slippage = self._fill_terms(
                        raw_price, quantity, side
                    )
                    notional = fill_price * quantity
                if notional + commission > cash:
                    raise PaperLedgerError("paper affordability calculation produced negative cash")
                cash -= notional + commission  # fill price embeds spread/slippage.
            else:
                quantity = requested
                cash += notional - commission
            positions[symbol] = positions.get(symbol, Decimal("0")) + (
                quantity if side is Side.BUY else -quantity
            )
            fill_id = self._stable_id(f"fill:{order_id}:{trading_date.isoformat()}")
            self._append_event(
                connection,
                fill_id,
                "fill",
                trading_date,
                _fill_payload(
                    PaperFill(
                        fill_id,
                        str(order_id),
                        trading_date,
                        symbol,
                        side,
                        quantity,
                        raw_price,
                        fill_price,
                        notional,
                        commission,
                        spread,
                        slippage,
                        manifest_id,
                    )
                ),
            )

    def _fill_terms(
        self, raw_price: Decimal, quantity: Decimal, side: Side
    ) -> tuple[Decimal, Decimal, Decimal, Decimal]:
        if raw_price <= 0:
            raise PaperLedgerError("raw price must be positive")
        rate = self.config.costs.half_spread_rate + self.config.costs.slippage_rate
        fill_price = raw_price * (Decimal("1") + rate if side is Side.BUY else Decimal("1") - rate)
        notional = fill_price * quantity
        commission = max(
            notional * self.config.costs.commission_rate, self.config.costs.minimum_commission
        )
        return (
            fill_price,
            commission,
            raw_price * quantity * self.config.costs.half_spread_rate,
            raw_price * quantity * self.config.costs.slippage_rate,
        )

    def _affordable_quantity(self, cash: Decimal, raw_price: Decimal) -> Decimal:
        # Solve with the minimum-commission branch conservatively; Decimal permits fractional units.
        rate = self.config.costs.half_spread_rate + self.config.costs.slippage_rate
        unit = raw_price * (Decimal("1") + rate)
        if cash <= self.config.costs.minimum_commission:
            return Decimal("0")
        quantity = (cash - self.config.costs.minimum_commission) / unit
        if (
            unit * quantity * self.config.costs.commission_rate
            > self.config.costs.minimum_commission
        ):
            quantity = cash / (unit * (Decimal("1") + self.config.costs.commission_rate))
        return max(quantity, Decimal("0"))

    def _append_snapshot(
        self,
        connection: sqlite3.Connection,
        run_id: str,
        trading_date: date,
        raw_closes: Mapping[str, Decimal],
        manifest_id: str,
        state: PaperSnapshot,
    ) -> PaperSnapshot:
        if set(state.positions) - set(raw_closes):
            raise PaperLedgerError("raw close missing for a held position")
        nav = state.cash + sum(
            (quantity * raw_closes[symbol] for symbol, quantity in state.positions.items()),
            Decimal("0"),
        )
        snapshot = PaperSnapshot(
            trading_date, state.cash, dict(state.positions), nav, state.cumulative_fees, run_id
        )
        self._append_event(
            connection,
            self._stable_id(f"snapshot:{run_id}"),
            "snapshot",
            trading_date,
            {
                **_snapshot_payload(snapshot),
                "raw_closes": {key: _text(value) for key, value in sorted(raw_closes.items())},
                "manifest_id": manifest_id,
            },
        )
        return snapshot

    def _rebuild(self, connection: sqlite3.Connection) -> PaperSnapshot:
        cash = Decimal("0")
        positions: dict[str, Decimal] = {}
        fees = Decimal("0")
        last: PaperSnapshot | None = None
        previous = _GENESIS_HASH
        for (
            sequence,
            event_id,
            event_type,
            occurred_on,
            payload_text,
            prev_hash,
            event_hash,
        ) in connection.execute(
            "SELECT sequence,event_id,event_type,occurred_on,payload,prev_hash,event_hash "
            "FROM events ORDER BY sequence"
        ):
            if prev_hash != previous or event_hash != _event_hash(
                event_id, event_type, occurred_on, payload_text, prev_hash
            ):
                raise PaperLedgerError(f"invalid hash chain at event sequence {sequence}")
            previous = event_hash
            payload = json.loads(payload_text)
            if event_type == "initial_cash":
                cash += Decimal(payload["cash"])
            elif event_type == "fill":
                side = Side(payload["side"])
                quantity = Decimal(payload["quantity"])
                symbol = payload["symbol"]
                positions[symbol] = positions.get(symbol, Decimal("0")) + (
                    quantity if side is Side.BUY else -quantity
                )
                cash += (
                    -(Decimal(payload["notional"]) + Decimal(payload["commission"]))
                    if side is Side.BUY
                    else Decimal(payload["notional"]) - Decimal(payload["commission"])
                )
                fees += (
                    Decimal(payload["commission"])
                    + Decimal(payload["spread_cost"])
                    + Decimal(payload["slippage_cost"])
                )
            elif event_type == "split":
                positions[payload["symbol"]] = positions.get(
                    payload["symbol"], Decimal("0")
                ) * Decimal(payload["ratio"])
            elif event_type == "dividend_payment":
                cash += Decimal(payload["cash"])
            elif event_type == "snapshot":
                last = _snapshot_from_payload(payload)
                expected_at_snapshot = cash + sum(
                    (
                        positions.get(symbol, Decimal("0")) * Decimal(price)
                        for symbol, price in payload["raw_closes"].items()
                    ),
                    Decimal("0"),
                )
                if (
                    last.cash != cash
                    or dict(last.positions) != positions
                    or last.net_asset_value != expected_at_snapshot
                    or last.cumulative_fees != fees
                ):
                    raise PaperLedgerError("snapshot does not reconcile to immutable events")
            if cash < 0 or any(quantity < 0 for quantity in positions.values()):
                raise PaperLedgerError("ledger replay produced negative cash or position")
        if last is None:
            return PaperSnapshot(date.min, cash, positions, cash, fees, "")
        expected_nav = cash + sum(
            (
                positions.get(symbol, Decimal("0")) * Decimal(price)
                for symbol, price in _snapshot_prices(connection, last.run_id).items()
            ),
            Decimal("0"),
        )
        return PaperSnapshot(last.as_of_date, cash, positions, expected_nav, fees, last.run_id)

    def _validate_prices(
        self, raw_opens: Mapping[str, Decimal], raw_closes: Mapping[str, Decimal]
    ) -> None:
        if (
            not raw_opens
            or not raw_closes
            or any(value <= 0 for value in (*raw_opens.values(), *raw_closes.values()))
        ):
            raise ValueError("raw opens and closes must be non-empty positive prices")

    def _stable_id(self, purpose: str) -> str:
        return str(uuid5(NAMESPACE_URL, f"quant-stack/paper/{self.config.account_id}/{purpose}"))

    def _action_id(self, action: CorporateActionEvent) -> str:
        return self._stable_id(
            f"action:{action.effective_date.isoformat()}:{action.kind.value}:{action.cash_per_unit}:{action.split_ratio}"
        )


def _snapshot_prices(connection: sqlite3.Connection, run_id: str) -> Mapping[str, str]:
    """Load the matching immutable raw-close valuation payload for a snapshot."""
    rows = connection.execute(
        "SELECT payload FROM events WHERE event_type = 'snapshot' ORDER BY sequence DESC"
    )
    for row in rows:
        payload = json.loads(row[0])
        if payload["run_id"] == run_id:
            return {str(key): str(value) for key, value in payload["raw_closes"].items()}
    raise PaperLedgerError("missing raw-close evidence for snapshot")


def _event_hash(
    event_id: str, event_type: str, occurred_on: str | None, payload: str, previous: str
) -> str:
    """Return the content-addressed chain hash for one exact serialized event."""
    return hashlib.sha256(
        "|".join((event_id, event_type, occurred_on or "", payload, previous)).encode()
    ).hexdigest()


def _text(value: Decimal) -> str:
    """Serialize Decimal without binary float conversion."""
    return str(value)


def _fill_payload(fill: PaperFill) -> dict[str, str]:
    return {
        "fill_id": fill.fill_id,
        "order_id": fill.order_id,
        "trading_date": fill.trading_date.isoformat(),
        "symbol": fill.symbol,
        "side": fill.side.value,
        "quantity": _text(fill.quantity),
        "raw_reference_price": _text(fill.raw_reference_price),
        "fill_price": _text(fill.fill_price),
        "notional": _text(fill.notional),
        "commission": _text(fill.commission),
        "spread_cost": _text(fill.spread_cost),
        "slippage_cost": _text(fill.slippage_cost),
        "manifest_id": fill.manifest_id,
    }


def _fill_from_payload(payload: Mapping[str, str]) -> PaperFill:
    return PaperFill(
        payload["fill_id"],
        payload["order_id"],
        date.fromisoformat(payload["trading_date"]),
        payload["symbol"],
        Side(payload["side"]),
        Decimal(payload["quantity"]),
        Decimal(payload["raw_reference_price"]),
        Decimal(payload["fill_price"]),
        Decimal(payload["notional"]),
        Decimal(payload["commission"]),
        Decimal(payload["spread_cost"]),
        Decimal(payload["slippage_cost"]),
        payload["manifest_id"],
    )


def _order_from_payload(order_id: str, payload: Mapping[str, str]) -> PaperOrder:
    """Rebuild one stored order payload without deriving a new identifier."""
    return PaperOrder(
        order_id,
        payload["symbol"],
        Side(payload["side"]),
        Decimal(payload["quantity"]),
        date.fromisoformat(payload["signal_date"]),
        date.fromisoformat(payload["earliest_execution_date"]),
    )


def _snapshot_payload(snapshot: PaperSnapshot) -> dict[str, Any]:
    return {
        "as_of_date": snapshot.as_of_date.isoformat(),
        "cash": _text(snapshot.cash),
        "positions": {key: _text(value) for key, value in sorted(snapshot.positions.items())},
        "net_asset_value": _text(snapshot.net_asset_value),
        "cumulative_fees": _text(snapshot.cumulative_fees),
        "run_id": snapshot.run_id,
    }


def _snapshot_from_payload(payload: Mapping[str, Any]) -> PaperSnapshot:
    return PaperSnapshot(
        date.fromisoformat(payload["as_of_date"]),
        Decimal(payload["cash"]),
        {key: Decimal(value) for key, value in payload["positions"].items()},
        Decimal(payload["net_asset_value"]),
        Decimal(payload["cumulative_fees"]),
        str(payload["run_id"]),
    )
