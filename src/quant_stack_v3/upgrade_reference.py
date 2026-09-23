"""Independent economic reference calculation for selected upgrade runs."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from hashlib import sha256
from pathlib import Path

import pandas as pd

from quant_stack.data.models import CorporateActionEvent, CorporateActionKind
from quant_stack.research_json import canonical_json
from quant_stack.snapshot import write_immutable
from quant_stack_v3.actions import load_actions
from quant_stack_v3.protocol import Protocol


@dataclass(frozen=True)
class ReferenceOrder:
    """Order intent consumed by the independent reference account."""

    order_id: str
    symbol: str
    side: str
    quantity: Decimal
    signal_date: date
    execution_date: date


@dataclass(frozen=True)
class ReferenceCosts:
    """Dated cost inputs duplicated independently from the primary engine."""

    commission_rate: Decimal
    minimum_commission: Decimal
    half_spread_rate: Decimal
    slippage_rate: Decimal
    sell_tax_rate: Decimal
    transfer_fee_rate: Decimal


def audit_reference_run(
    *,
    primary_run_root: Path,
    bundle_root: Path,
    bundle_sha256: str,
    bars_path: Path,
    base_protocol: Protocol,
    output_root: Path,
) -> tuple[Path, dict[str, object]]:
    """Recompute fills, corporate actions, cash, positions and NAV without primary code."""
    result = json.loads((primary_run_root / "result.json").read_text(encoding="utf-8"))
    experiment = _mapping(_mapping(result["identities"])["experiment"])
    initial_cash = Decimal(str(experiment["initial_cash"]))
    cost_mode = str(experiment["cost_mode"])
    ledger = pd.read_parquet(primary_run_root / "ledger.parquet").sort_values("sequence")
    orders = tuple(
        ReferenceOrder(
            order_id=str(payload["order_id"]),
            symbol=str(payload["symbol"]),
            side=str(payload["side"]),
            quantity=Decimal(str(payload["quantity"])),
            signal_date=date.fromisoformat(str(payload["signal_date"])),
            execution_date=date.fromisoformat(str(payload["execution_date"])),
        )
        for payload in (
            json.loads(str(value)) for value in ledger.loc[ledger.event_type == "order", "payload"]
        )
    )
    primary_fills = {
        str(value["order_id"]): value
        for value in (
            json.loads(str(item)) for item in ledger.loc[ledger.event_type == "fill", "payload"]
        )
    }
    primary_rejections = {
        str(value["order_id"]): value
        for value in (
            json.loads(str(item))
            for item in ledger.loc[ledger.event_type == "rejection", "payload"]
        )
    }
    primary_snapshots = {
        str(row.occurred_on): json.loads(str(row.payload))
        for row in ledger.loc[ledger.event_type == "snapshot"].itertuples(index=False)
    }
    sessions = tuple(date.fromisoformat(value) for value in primary_snapshots)
    bars = pd.read_parquet(bars_path).set_index(["session", "symbol"], drop=False).sort_index()
    actions, transfers = load_actions(
        bundle_root,
        bundle_sha256=bundle_sha256,
        start=sessions[0],
        end=sessions[-1],
    )
    cash = initial_cash
    positions: dict[str, Decimal] = {}
    receivable = Decimal("0")
    entitlements: dict[str, tuple[date, date, Decimal]] = {}
    accrued: set[str] = set()
    paid: set[str] = set()
    observed_fills: dict[str, dict[str, str]] = {}
    observed_rejections: dict[str, dict[str, str]] = {}
    snapshot_count = 0
    for session in sessions:
        for transfer in transfers.get(session, ()):
            quantity = positions.get(transfer.predecessor, Decimal("0"))
            if quantity > 0:
                positions[transfer.predecessor] = Decimal("0")
                positions[transfer.successor] = (
                    positions.get(transfer.successor, Decimal("0")) + quantity * transfer.ratio
                )
        session_actions = actions.get(session, {})
        for symbol, values in session_actions.items():
            for action in values:
                if (
                    action.kind is CorporateActionKind.SHARE_SPLIT
                    and action.effective_date == session
                ):
                    quantity = positions.get(symbol, Decimal("0"))
                    if quantity > 0:
                        positions[symbol] = quantity * Decimal(str(action.split_ratio))
        for identity, (effective, _, amount) in sorted(entitlements.items()):
            if identity not in accrued and effective <= session:
                receivable += amount
                accrued.add(identity)
        today = _daily_rows(bars, session)
        costs = _costs(base_protocol, session, cost_mode)
        due = sorted(
            (item for item in orders if item.execution_date == session),
            key=lambda item: (
                0 if item.side == "sell" else 1,
                item.symbol,
                item.signal_date,
                item.quantity,
            ),
        )
        for order in due:
            reason = _block_reason(order, today, session, session_actions)
            if reason is not None:
                observed_rejections[order.order_id] = {
                    "order_id": order.order_id,
                    "trading_date": session.isoformat(),
                    "symbol": order.symbol,
                    "reason": reason,
                }
                continue
            row = today.loc[order.symbol]
            raw = Decimal(str(row.raw_open))
            quantity = order.quantity
            if order.side == "sell":
                quantity = min(quantity, positions.get(order.symbol, Decimal("0")))
                if quantity <= 0:
                    observed_rejections[order.order_id] = {
                        "order_id": order.order_id,
                        "trading_date": session.isoformat(),
                        "symbol": order.symbol,
                        "reason": "insufficient_position",
                    }
                    continue
            else:
                minimum, increment = _lot_rule(str(row.board))
                quantity = min(
                    quantity,
                    _affordable(cash, raw, costs, minimum=minimum, increment=increment),
                )
                if quantity <= 0:
                    observed_rejections[order.order_id] = {
                        "order_id": order.order_id,
                        "trading_date": session.isoformat(),
                        "symbol": order.symbol,
                        "reason": "insufficient_cash",
                    }
                    continue
            fill = _fill(order, session, raw, quantity, costs)
            notional = Decimal(fill["notional"])
            commission = Decimal(fill["commission"])
            tax = Decimal(fill["tax_cost"])
            transfer_fee = Decimal(fill["transfer_fee"])
            if order.side == "buy":
                cash -= notional + commission + transfer_fee
                positions[order.symbol] = positions.get(order.symbol, Decimal("0")) + quantity
            else:
                cash += notional - commission - tax - transfer_fee
                positions[order.symbol] = positions.get(order.symbol, Decimal("0")) - quantity
            observed_fills[order.order_id] = fill
        for symbol, values in session_actions.items():
            for action in values:
                if (
                    action.kind is CorporateActionKind.CASH_DISTRIBUTION
                    and action.record_date == session
                ):
                    quantity = positions.get(symbol, Decimal("0"))
                    if quantity <= 0:
                        continue
                    if action.payment_date is None or action.cash_per_unit is None:
                        raise ValueError("reference held dividend lacks payment or cash value")
                    identity = sha256(
                        f"{symbol}:{action.effective_date}:{action.cash_per_unit}".encode()
                    ).hexdigest()
                    entitlements.setdefault(
                        identity,
                        (
                            action.effective_date,
                            action.payment_date,
                            quantity * action.cash_per_unit,
                        ),
                    )
        for identity, (effective, _, amount) in sorted(entitlements.items()):
            if identity not in accrued and effective <= session:
                receivable += amount
                accrued.add(identity)
        for identity, (_, payment, amount) in sorted(entitlements.items()):
            if identity in accrued and identity not in paid and payment <= session:
                cash += amount
                receivable -= amount
                paid.add(identity)
        held = {symbol for symbol, quantity in positions.items() if quantity > 0}
        missing = held - set(today.index)
        if missing:
            raise ValueError(
                f"reference held valuation missing on {session}: {', '.join(sorted(missing))}"
            )
        nav = (
            cash
            + receivable
            + sum(
                (positions[symbol] * Decimal(str(today.loc[symbol].raw_close)) for symbol in held),
                Decimal("0"),
            )
        )
        expected = primary_snapshots[session.isoformat()]
        expected_positions = {
            key: Decimal(str(value)) for key, value in _mapping(expected["positions"]).items()
        }
        if (
            cash != Decimal(str(expected["cash"]))
            or receivable != Decimal(str(expected["receivable_dividends"]))
            or positions != expected_positions
            or nav != Decimal(str(expected["net_asset_value"]))
        ):
            raise ValueError(f"independent reference snapshot differs on {session}")
        snapshot_count += 1
    _compare_execution(primary_fills, observed_fills, "fill")
    _compare_execution(primary_rejections, observed_rejections, "rejection")
    report: dict[str, object] = {
        "schema_version": 1,
        "status": "INDEPENDENT_ECONOMIC_REFERENCE_PASS",
        "run_identity": result["run_identity"],
        "strategy_id": result["strategy_id"],
        "snapshot_count": snapshot_count,
        "fill_count": len(observed_fills),
        "rejection_count": len(observed_rejections),
        "final_cash": cash,
        "final_receivable": receivable,
        "final_positions": {key: value for key, value in sorted(positions.items()) if value > 0},
        "independence": [
            "does not import HistoricalAccount",
            "does not import primary fill or cost functions",
            "starts from frozen order intents rather than primary fills",
        ],
    }
    encoded = canonical_json(report) + b"\n"
    path = output_root / "reference" / f"{sha256(encoded).hexdigest()}.json"
    write_immutable(path, encoded)
    return path, report


def _fill(
    order: ReferenceOrder,
    session: date,
    raw: Decimal,
    quantity: Decimal,
    costs: ReferenceCosts,
) -> dict[str, str]:
    impact = costs.half_spread_rate + costs.slippage_rate
    fill_price = raw * (Decimal("1") + impact if order.side == "buy" else Decimal("1") - impact)
    notional = fill_price * quantity
    commission = max(notional * costs.commission_rate, costs.minimum_commission)
    spread = raw * quantity * costs.half_spread_rate
    slippage = raw * quantity * costs.slippage_rate
    tax = notional * costs.sell_tax_rate if order.side == "sell" else Decimal("0")
    transfer = notional * costs.transfer_fee_rate
    return {
        "order_id": order.order_id,
        "trading_date": session.isoformat(),
        "symbol": order.symbol,
        "side": order.side,
        "quantity": str(quantity),
        "raw_price": str(raw),
        "fill_price": str(fill_price),
        "notional": str(notional),
        "commission": str(commission),
        "spread_cost": str(spread),
        "slippage_cost": str(slippage),
        "tax_cost": str(tax),
        "transfer_fee": str(transfer),
    }


def _affordable(
    cash: Decimal,
    raw: Decimal,
    costs: ReferenceCosts,
    *,
    minimum: Decimal,
    increment: Decimal,
) -> Decimal:
    if cash <= costs.minimum_commission:
        return Decimal("0")
    impacted = raw * (Decimal("1") + costs.half_spread_rate + costs.slippage_rate)
    estimate = (cash - costs.minimum_commission) / (
        impacted * (Decimal("1") + costs.transfer_fee_rate)
    )
    quantity = _lot(estimate, minimum, increment)
    while quantity > 0:
        notional = impacted * quantity
        commission = max(notional * costs.commission_rate, costs.minimum_commission)
        if notional + commission + notional * costs.transfer_fee_rate <= cash:
            return quantity
        quantity -= increment
    return Decimal("0")


def _block_reason(
    order: ReferenceOrder,
    today: pd.DataFrame,
    session: date,
    actions: dict[str, tuple[CorporateActionEvent, ...]],
) -> str | None:
    if order.symbol in actions and any(
        item.effective_date == session for item in actions[order.symbol]
    ):
        return "corporate_action_execution_day"
    if order.symbol not in today.index:
        return "missing_open_or_suspended"
    row = today.loc[order.symbol]
    if bool(row.suspended):
        return "suspended"
    if (
        order.side == "buy"
        and float(row.limit_up) > 0
        and float(row.raw_open) >= float(row.limit_up)
    ):
        return "buy_open_at_upper_limit"
    if (
        order.side == "sell"
        and float(row.limit_down) > 0
        and float(row.raw_open) <= float(row.limit_down)
    ):
        return "sell_open_at_lower_limit"
    return None


def _costs(protocol: Protocol, session: date, mode: str) -> ReferenceCosts:
    transfer = (
        protocol.costs.transfer_fee_before_2022_04_29
        if session < date(2022, 4, 29)
        else protocol.costs.transfer_fee_from_2022_04_29
    )
    tax = (
        protocol.costs.sell_tax_before_2023_08_28
        if session < date(2023, 8, 28)
        else protocol.costs.sell_tax_from_2023_08_28
    )
    if mode == "zero_all":
        return ReferenceCosts(*(Decimal("0") for _ in range(6)))
    multiplier = Decimal("2") if mode == "double_assumption" else Decimal("1")
    return ReferenceCosts(
        protocol.costs.commission_rate * multiplier,
        protocol.costs.minimum_commission * multiplier,
        protocol.costs.half_spread_rate * multiplier,
        protocol.costs.slippage_rate * multiplier,
        tax,
        transfer,
    )


def _daily_rows(bars: pd.DataFrame, session: date) -> pd.DataFrame:
    try:
        rows = bars.loc[pd.Timestamp(session)]
    except KeyError:
        return pd.DataFrame(columns=bars.columns).set_index(pd.Index([], name="symbol"))
    if isinstance(rows, pd.Series):
        rows = rows.to_frame().T
    return rows.set_index("symbol", drop=False)


def _lot_rule(board: str) -> tuple[Decimal, Decimal]:
    return (
        (Decimal("200"), Decimal("1"))
        if board == "star"
        else (
            Decimal("100"),
            Decimal("100"),
        )
    )


def _lot(value: Decimal, minimum: Decimal, increment: Decimal) -> Decimal:
    if value < minimum:
        return Decimal("0")
    return minimum + ((value - minimum) // increment) * increment


def _compare_execution(
    expected: dict[str, dict[str, object]],
    observed: dict[str, dict[str, str]],
    kind: str,
) -> None:
    if set(expected) != set(observed):
        raise ValueError(f"independent reference {kind} identities differ")
    for identity, left in expected.items():
        right = observed[identity]
        for key, value in right.items():
            if str(left[key]) != str(value):
                raise ValueError(f"independent reference {kind} differs for {identity}:{key}")


def _mapping(value: object) -> dict[str, object]:
    if not isinstance(value, dict):
        raise ValueError("reference input field must be a mapping")
    return value
