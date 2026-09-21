"""Independent persisted-ledger replay for V3 real-run acceptance."""

from __future__ import annotations

import json
from collections import defaultdict
from decimal import Decimal
from hashlib import sha256
from pathlib import Path

import pandas as pd

from quant_stack.research_json import canonical_json
from quant_stack.snapshot import write_immutable


def audit_ledger(ledger_path: Path, output_root: Path) -> tuple[Path, dict[str, object]]:
    """Replay every persisted event and independently check all snapshot invariants."""
    events = pd.read_parquet(ledger_path).sort_values("sequence")
    cash = Decimal("0")
    positions: dict[str, Decimal] = {}
    receivable = Decimal("0")
    fees = Decimal("0")
    previous = "0" * 64
    snapshot_count = 0
    fill_sides: dict[str, set[str]] = defaultdict(set)
    first_fill: str | None = None
    first_entitlement: str | None = None
    first_payment: str | None = None
    first_split: str | None = None
    for row in events.itertuples(index=False):
        payload_text = str(row.payload)
        expected = sha256(
            "|".join((str(row.event_type), str(row.occurred_on), payload_text, previous)).encode()
        ).hexdigest()
        if row.prev_hash != previous or row.event_hash != expected:
            raise ValueError(f"persisted ledger hash mismatch at sequence {row.sequence}")
        previous = expected
        payload = json.loads(payload_text)
        event_type = str(row.event_type)
        occurred_on = str(row.occurred_on)
        if event_type == "initial_cash":
            cash += Decimal(payload["cash"])
        elif event_type == "fill":
            side = str(payload["side"])
            symbol = str(payload["symbol"])
            quantity = Decimal(payload["quantity"])
            notional = Decimal(payload["notional"])
            commission = Decimal(payload["commission"])
            tax = Decimal(payload["tax_cost"])
            transfer = Decimal(payload["transfer_fee"])
            if side == "buy":
                positions[symbol] = positions.get(symbol, Decimal("0")) + quantity
                cash -= notional + commission + transfer
            else:
                positions[symbol] = positions.get(symbol, Decimal("0")) - quantity
                cash += notional - commission - tax - transfer
            fees += (
                commission
                + Decimal(payload["spread_cost"])
                + Decimal(payload["slippage_cost"])
                + tax
                + transfer
            )
            fill_sides[occurred_on].add(side)
            first_fill = first_fill or occurred_on
        elif event_type == "split":
            symbol = str(payload["symbol"])
            positions[symbol] = positions.get(symbol, Decimal("0")) * Decimal(payload["ratio"])
            first_split = first_split or occurred_on
        elif event_type == "position_transfer":
            predecessor = str(payload["predecessor"])
            successor = str(payload["successor"])
            quantity = positions.get(predecessor, Decimal("0"))
            positions[predecessor] = Decimal("0")
            positions[successor] = positions.get(successor, Decimal("0")) + quantity * Decimal(
                payload["ratio"]
            )
        elif event_type == "entitlement":
            amount = Decimal(payload["quantity"]) * Decimal(payload["cash_per_unit"])
            receivable += amount
            first_entitlement = first_entitlement or occurred_on
        elif event_type == "dividend_payment":
            amount = Decimal(payload["cash"])
            cash += amount
            receivable -= amount
            first_payment = first_payment or occurred_on
        elif event_type == "snapshot":
            expected_positions = {
                key: Decimal(value) for key, value in payload["positions"].items()
            }
            raw_closes = {key: Decimal(value) for key, value in payload["raw_closes"].items()}
            nav = (
                cash
                + receivable
                + sum(
                    (
                        quantity * raw_closes[symbol]
                        for symbol, quantity in positions.items()
                        if quantity > 0
                    ),
                    Decimal("0"),
                )
            )
            if (
                Decimal(payload["cash"]) != cash
                or expected_positions != positions
                or Decimal(payload["net_asset_value"]) != nav
                or Decimal(payload["cumulative_fees"]) != fees
                or Decimal(payload["receivable_dividends"]) != receivable
            ):
                raise ValueError(f"persisted snapshot does not reconcile on {occurred_on}")
            snapshot_count += 1
    two_sided = next(
        (session for session, sides in sorted(fill_sides.items()) if sides == {"buy", "sell"}),
        None,
    )
    report: dict[str, object] = {
        "schema_version": 1,
        "status": "INDEPENDENT_LEDGER_REPLAY_PASS",
        "ledger_sha256": _file_sha256(ledger_path),
        "event_count": len(events),
        "snapshot_count": snapshot_count,
        "ledger_head": previous,
        "first_fill_date": first_fill,
        "first_two_sided_rebalance_date": two_sided,
        "first_entitlement_date": first_entitlement,
        "first_dividend_payment_date": first_payment,
        "first_split_date": first_split,
        "final_cash": cash,
        "final_receivable": receivable,
        "final_cumulative_fees": fees,
    }
    encoded = canonical_json(report) + b"\n"
    path = output_root / "acceptance" / f"{sha256(encoded).hexdigest()}.json"
    write_immutable(path, encoded)
    return path, report


def _file_sha256(path: Path) -> str:
    digest = sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()
