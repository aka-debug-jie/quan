"""Offline regression coverage for the local SQLite paper broker."""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest

from quant_stack.costs import CostModel
from quant_stack.data.models import CorporateActionEvent, CorporateActionKind, OfficialEvidence
from quant_stack.models import Side
from quant_stack.paper_broker import PaperBroker, PaperLedgerError
from quant_stack.paper_models import PaperBrokerConfig, PaperOrder


def _broker(tmp_path: Path) -> PaperBroker:
    return PaperBroker(
        tmp_path / "paper.sqlite",
        PaperBrokerConfig(
            "test-account",
            CostModel(Decimal("0.001"), Decimal("5"), Decimal("0.0001"), Decimal("0.0002")),
        ),
    )


def _order() -> PaperOrder:
    return PaperOrder(
        "buy-etf",
        "ETF",
        Side.BUY,
        Decimal("100"),
        date(2026, 1, 2),
        date(2026, 1, 5),
    )


def _action(
    kind: CorporateActionKind,
    *,
    effective: date,
    cash: Decimal | None = None,
    ratio: Decimal | None = None,
    record: date | None = None,
    payment: date | None = None,
) -> CorporateActionEvent:
    return CorporateActionEvent(
        effective_date=effective,
        kind=kind,
        cash_per_unit=cash,
        split_ratio=ratio,
        evidence=OfficialEvidence(
            url="https://example.test/evidence", sha256="a" * 64, published_on=effective
        ),
        record_date=record,
        payment_date=payment,
    )


def test_initialization_raw_open_fill_and_repeat_run_are_idempotent(tmp_path: Path) -> None:
    broker = _broker(tmp_path)
    assert broker.initialize().cash == Decimal("100000")
    broker.place_order(_order())

    first = broker.run_daily(
        "day-one", date(2026, 1, 5), {"ETF": Decimal("10")}, {"ETF": Decimal("11")}, "b" * 64
    )
    repeated = broker.run_daily(
        "day-one", date(2026, 1, 5), {"ETF": Decimal("10")}, {"ETF": Decimal("11")}, "b" * 64
    )

    fill = broker.fills()[0]
    assert repeated == first
    assert fill.raw_reference_price == Decimal("10")
    assert fill.fill_price == Decimal("10.003")
    assert fill.quantity == Decimal("100")
    assert first.net_asset_value == first.cash + Decimal("1100")
    assert broker.reconcile().snapshot == first


def test_dividend_record_payment_and_split_rebuild_exact_state(tmp_path: Path) -> None:
    broker = _broker(tmp_path)
    broker.initialize()
    broker.place_order(_order())
    broker.run_daily(
        "buy", date(2026, 1, 5), {"ETF": Decimal("10")}, {"ETF": Decimal("10")}, "c" * 64
    )
    dividend = _action(
        CorporateActionKind.CASH_DISTRIBUTION,
        effective=date(2026, 1, 6),
        cash=Decimal("0.25"),
        record=date(2026, 1, 6),
        payment=date(2026, 1, 7),
    )
    broker.run_daily(
        "record",
        date(2026, 1, 6),
        {"ETF": Decimal("10")},
        {"ETF": Decimal("10")},
        "d" * 64,
        {"ETF": (dividend,)},
    )
    paid = broker.run_daily(
        "payment",
        date(2026, 1, 7),
        {"ETF": Decimal("10")},
        {"ETF": Decimal("10")},
        "e" * 64,
        {"ETF": (dividend,)},
    )
    split = _action(
        CorporateActionKind.SHARE_SPLIT,
        effective=date(2026, 1, 8),
        ratio=Decimal("2"),
    )
    final = broker.run_daily(
        "split",
        date(2026, 1, 8),
        {"ETF": Decimal("5")},
        {"ETF": Decimal("5")},
        "f" * 64,
        {"ETF": (split,)},
    )

    assert paid.cash > Decimal("99000")
    assert final.positions == {"ETF": Decimal("200")}
    assert broker.reconcile().snapshot == final


def test_held_dividend_without_payment_date_stops_before_snapshot(tmp_path: Path) -> None:
    broker = _broker(tmp_path)
    broker.initialize()
    broker.place_order(_order())
    broker.run_daily(
        "buy", date(2026, 1, 5), {"ETF": Decimal("10")}, {"ETF": Decimal("10")}, "a" * 64
    )
    unknown_payment = _action(
        CorporateActionKind.CASH_DISTRIBUTION,
        effective=date(2026, 1, 6),
        cash=Decimal("0.1"),
        record=date(2026, 1, 6),
    )
    with pytest.raises(PaperLedgerError, match="lacks payment_date"):
        broker.run_daily(
            "bad",
            date(2026, 1, 6),
            {"ETF": Decimal("10")},
            {"ETF": Decimal("10")},
            "a" * 64,
            {"ETF": (unknown_payment,)},
        )


def test_unaffordable_order_is_recorded_as_rejection(tmp_path: Path) -> None:
    broker = _broker(tmp_path)
    broker.initialize()
    broker.place_order(
        PaperOrder(
            "consume-cash", "ETF", Side.BUY, Decimal("1000000"), date(2026, 1, 2), date(2026, 1, 5)
        )
    )
    broker.place_order(
        PaperOrder("too-large", "ETF", Side.BUY, Decimal("1"), date(2026, 1, 2), date(2026, 1, 5))
    )
    broker.run_daily(
        "rejected", date(2026, 1, 5), {"ETF": Decimal("10")}, {"ETF": Decimal("10")}, "d" * 64
    )
    assert broker.rejections()[0].reason == "insufficient_cash"
    assert len(broker.fills()) == 1
