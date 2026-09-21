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
from quant_stack.paper_models import PaperBrokerConfig, PaperExecutionRule, PaperOrder


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
    record = broker.run_daily(
        "record",
        date(2026, 1, 6),
        {"ETF": Decimal("10")},
        {"ETF": Decimal("10")},
        "d" * 64,
        {"ETF": (dividend,)},
    )
    paid = broker.run_daily(
        "payment",
        date(2026, 1, 8),
        {"ETF": Decimal("10")},
        {"ETF": Decimal("10")},
        "e" * 64,
        {"ETF": (dividend,)},
    )
    split = _action(
        CorporateActionKind.SHARE_SPLIT,
        effective=date(2026, 1, 9),
        ratio=Decimal("2"),
    )
    final = broker.run_daily(
        "split",
        date(2026, 1, 9),
        {"ETF": Decimal("5")},
        {"ETF": Decimal("5")},
        "f" * 64,
        {"ETF": (split,)},
    )

    assert record.receivable_dividends == Decimal("25.00")
    assert paid.receivable_dividends == Decimal("0")
    assert paid.net_asset_value == record.net_asset_value
    assert paid.cash > Decimal("99000")
    assert final.positions == {"ETF": Decimal("200")}
    assert broker.reconcile().snapshot == final


def test_provider_declared_position_transfer_preserves_share_value(tmp_path: Path) -> None:
    broker = _broker(tmp_path)
    broker.initialize()
    broker.place_order(_order())
    broker.run_daily(
        "buy-old", date(2026, 1, 5), {"ETF": Decimal("10")}, {"ETF": Decimal("10")}, "a" * 64
    )
    broker.transfer_position(
        "provider-transfer",
        date(2026, 1, 6),
        "ETF",
        "NEW",
        Decimal("2"),
    )
    final = broker.run_daily(
        "after-transfer",
        date(2026, 1, 6),
        {"NEW": Decimal("5")},
        {"NEW": Decimal("5")},
        "b" * 64,
    )
    assert final.positions == {"NEW": Decimal("200")}
    assert final.net_asset_value < Decimal("100000")
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


def test_board_quantity_and_sell_only_taxes_are_recorded(tmp_path: Path) -> None:
    broker = PaperBroker(
        tmp_path / "taxed.sqlite",
        PaperBrokerConfig(
            "taxed",
            CostModel(
                Decimal("0.0003"),
                Decimal("5"),
                Decimal("0"),
                Decimal("0"),
                Decimal("0.0005"),
                Decimal("0.00001"),
            ),
            Decimal("100000"),
        ),
    )
    broker.initialize()
    broker.place_order(
        PaperOrder(
            "star-buy", "sh688001", Side.BUY, Decimal("201"), date(2026, 1, 2), date(2026, 1, 5)
        )
    )
    broker.run_daily(
        "buy-star",
        date(2026, 1, 5),
        {"sh688001": Decimal("10")},
        {"sh688001": Decimal("10")},
        "a" * 64,
        execution_rules={"sh688001": PaperExecutionRule(Decimal("200"), Decimal("1"))},
    )
    bought = broker.fills()[0]
    assert bought.tax_cost == 0
    assert bought.transfer_fee > 0
    broker.place_order(
        PaperOrder(
            "star-sell", "sh688001", Side.SELL, Decimal("201"), date(2026, 1, 5), date(2026, 1, 6)
        )
    )
    broker.run_daily(
        "sell-star",
        date(2026, 1, 6),
        {"sh688001": Decimal("10")},
        {"sh688001": Decimal("10")},
        "b" * 64,
        execution_rules={"sh688001": PaperExecutionRule(Decimal("200"), Decimal("1"))},
    )
    assert broker.fills()[-1].tax_cost > 0


def test_invalid_board_buy_quantity_expires_without_fill(tmp_path: Path) -> None:
    broker = _broker(tmp_path)
    broker.initialize()
    broker.place_order(
        PaperOrder("bad-lot", "ETF", Side.BUY, Decimal("150"), date(2026, 1, 2), date(2026, 1, 5))
    )
    broker.run_daily(
        "bad-lot-day",
        date(2026, 1, 5),
        {"ETF": Decimal("10")},
        {"ETF": Decimal("10")},
        "d" * 64,
        execution_rules={"ETF": PaperExecutionRule(Decimal("100"), Decimal("100"))},
    )
    assert broker.fills() == ()
    assert broker.rejections()[0].reason == "invalid_board_quantity"


def test_same_day_rebalance_sells_before_buys_even_when_buy_was_written_first(
    tmp_path: Path,
) -> None:
    broker = _broker(tmp_path)
    broker.initialize()
    broker.place_order(
        PaperOrder("buy-old", "OLD", Side.BUY, Decimal("9000"), date(2026, 1, 2), date(2026, 1, 5))
    )
    broker.run_daily(
        "initial-position",
        date(2026, 1, 5),
        {"OLD": Decimal("10")},
        {"OLD": Decimal("10")},
        "a" * 64,
    )
    broker.place_order(
        PaperOrder("buy-new", "NEW", Side.BUY, Decimal("9000"), date(2026, 1, 5), date(2026, 1, 6))
    )
    broker.place_order(
        PaperOrder(
            "sell-old",
            "OLD",
            Side.SELL,
            Decimal("9000"),
            date(2026, 1, 5),
            date(2026, 1, 6),
        )
    )

    snapshot = broker.run_daily(
        "rebalance",
        date(2026, 1, 6),
        {"NEW": Decimal("10"), "OLD": Decimal("10")},
        {"NEW": Decimal("10"), "OLD": Decimal("10")},
        "b" * 64,
    )

    day_fills = [fill for fill in broker.fills() if fill.trading_date == date(2026, 1, 6)]
    assert [fill.side for fill in day_fills] == [Side.SELL, Side.BUY]
    assert day_fills[1].quantity == Decimal("9000")
    assert snapshot.positions == {"OLD": Decimal("0"), "NEW": Decimal("9000")}
    assert broker.reconcile().snapshot == snapshot


def test_record_date_entitlement_uses_post_fill_close_holdings(tmp_path: Path) -> None:
    dividend = _action(
        CorporateActionKind.CASH_DISTRIBUTION,
        effective=date(2026, 1, 5),
        cash=Decimal("0.25"),
        record=date(2026, 1, 5),
        payment=date(2026, 1, 6),
    )
    buyer = _broker(tmp_path / "buyer")
    buyer.initialize()
    buyer.place_order(_order())
    bought = buyer.run_daily(
        "record-buy",
        date(2026, 1, 5),
        {"ETF": Decimal("10")},
        {"ETF": Decimal("10")},
        "b" * 64,
        {"ETF": (dividend,)},
    )
    assert bought.receivable_dividends == Decimal("25.00")

    seller = _broker(tmp_path / "seller")
    seller.initialize()
    seller.place_order(_order())
    seller.run_daily(
        "buy-before", date(2026, 1, 5), {"ETF": Decimal("10")}, {"ETF": Decimal("10")}, "c" * 64
    )
    seller.place_order(
        PaperOrder(
            "sell-record", "ETF", Side.SELL, Decimal("100"), date(2026, 1, 5), date(2026, 1, 6)
        )
    )
    sold = seller.run_daily(
        "record-sell",
        date(2026, 1, 6),
        {"ETF": Decimal("10")},
        {"ETF": Decimal("10")},
        "d" * 64,
        {
            "ETF": (
                _action(
                    CorporateActionKind.CASH_DISTRIBUTION,
                    effective=date(2026, 1, 6),
                    cash=Decimal("0.25"),
                    record=date(2026, 1, 6),
                    payment=date(2026, 1, 7),
                ),
            )
        },
    )
    assert sold.positions["ETF"] == Decimal("0")
    assert sold.receivable_dividends == Decimal("0")
