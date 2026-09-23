"""Independent equivalence checks against the existing PaperBroker accounting."""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from pathlib import Path

from quant_stack.costs import CostModel
from quant_stack.data.models import (
    CorporateActionEvent,
    CorporateActionKind,
    OfficialEvidence,
)
from quant_stack.models import Side
from quant_stack.paper_broker import PaperBroker
from quant_stack.paper_models import PaperBrokerConfig, PaperExecutionRule, PaperOrder
from quant_stack_v3.fast_engine import HistoricalAccount, HistoricalOrder


def test_single_pass_engine_matches_paper_broker_buy_accounting(tmp_path: Path) -> None:
    costs = CostModel(
        Decimal("0.0003"),
        Decimal("5"),
        Decimal("0.0005"),
        Decimal("0.0005"),
        Decimal("0.001"),
        Decimal("0.00002"),
    )
    signal = date(2020, 1, 2)
    execution = date(2020, 1, 3)
    rule = PaperExecutionRule(Decimal("100"), Decimal("100"))
    paper = PaperBroker(
        tmp_path / "paper.sqlite3",
        PaperBrokerConfig("reference", costs, Decimal("100000")),
    )
    paper.initialize()
    paper.place_order(PaperOrder("order", "sh600000", Side.BUY, Decimal("100"), signal, execution))
    paper_snapshot = paper.run_daily(
        "run",
        execution,
        {"sh600000": Decimal("10")},
        {"sh600000": Decimal("11")},
        "a" * 64,
        execution_rules={"sh600000": rule},
    )
    fast = HistoricalAccount("fast", Decimal("100000"))
    fast.place_order(
        HistoricalOrder("order", "sh600000", Side.BUY, Decimal("100"), signal, execution)
    )
    fast_snapshot = fast.run_day(
        execution,
        {"sh600000": Decimal("10")},
        {"sh600000": Decimal("11")},
        costs,
        {},
        {},
        {"sh600000": rule},
    )
    assert fast_snapshot.cash == paper_snapshot.cash
    assert fast_snapshot.positions == dict(paper_snapshot.positions)
    assert fast_snapshot.net_asset_value == paper_snapshot.net_asset_value
    assert fast.fills[0].commission == paper.fills()[0].commission
    assert fast.fills[0].transfer_fee == paper.fills()[0].transfer_fee
    assert fast.reconcile().event_count > 0


def test_overlapping_delayed_sells_cannot_create_short_position() -> None:
    costs = CostModel(Decimal("0"), Decimal("0"), Decimal("0"), Decimal("0"))
    account = HistoricalAccount("delayed", Decimal("1000"))
    account.positions["sh600000"] = Decimal("100")
    execution = date(2020, 1, 3)
    account.place_order(
        HistoricalOrder(
            "sell-one",
            "sh600000",
            Side.SELL,
            Decimal("100"),
            date(2020, 1, 1),
            execution,
        )
    )
    account.place_order(
        HistoricalOrder(
            "sell-two",
            "sh600000",
            Side.SELL,
            Decimal("100"),
            date(2020, 1, 2),
            execution,
        )
    )
    snapshot = account.run_day(
        execution,
        {"sh600000": Decimal("10")},
        {"sh600000": Decimal("10")},
        costs,
        {},
        {},
        {"sh600000": PaperExecutionRule(Decimal("100"), Decimal("100"))},
    )
    assert snapshot.positions["sh600000"] == 0
    assert account.rejections[0].reason == "insufficient_position"


def test_cash_limited_buy_priority_does_not_depend_on_run_hash_order_ids() -> None:
    """Changing content identities must not change which symbol receives scarce cash."""
    costs = CostModel(Decimal("0"), Decimal("0"), Decimal("0"), Decimal("0"))
    signal = date(2020, 1, 2)
    execution = date(2020, 1, 3)
    prices = {"sh600000": Decimal("10"), "sh600001": Decimal("10")}
    rules = {symbol: PaperExecutionRule(Decimal("100"), Decimal("100")) for symbol in prices}
    outcomes = []
    for first_id, second_id in (("z-order", "a-order"), ("a-order", "z-order")):
        account = HistoricalAccount("same-policy", Decimal("1000"))
        account.place_order(
            HistoricalOrder(first_id, "sh600000", Side.BUY, Decimal("100"), signal, execution)
        )
        account.place_order(
            HistoricalOrder(second_id, "sh600001", Side.BUY, Decimal("100"), signal, execution)
        )
        snapshot = account.run_day(execution, prices, prices, costs, {}, {}, rules)
        outcomes.append((snapshot.positions, snapshot.cash, account.fills[0].symbol))
    assert outcomes[0] == outcomes[1]
    assert outcomes[0][2] == "sh600000"


def test_dividend_is_captured_on_record_date_and_accrued_on_ex_date() -> None:
    costs = CostModel(Decimal("0"), Decimal("0"), Decimal("0"), Decimal("0"))
    account = HistoricalAccount("dividend", Decimal("1000"))
    account.positions["sh600000"] = Decimal("100")
    record_date = date(2020, 1, 2)
    ex_date = date(2020, 1, 3)
    payment_date = date(2020, 1, 6)
    action = CorporateActionEvent(
        effective_date=ex_date,
        kind=CorporateActionKind.CASH_DISTRIBUTION,
        cash_per_unit=Decimal("0.5"),
        evidence=OfficialEvidence(
            url="https://example.invalid/action",
            sha256="a" * 64,
            published_on=record_date,
        ),
        record_date=record_date,
        payment_date=payment_date,
        retrospective_verification=True,
    )
    rule = {"sh600000": PaperExecutionRule(Decimal("100"), Decimal("100"))}
    record = account.run_day(
        record_date,
        {"sh600000": Decimal("10")},
        {"sh600000": Decimal("10")},
        costs,
        {"sh600000": (action,)},
        {},
        rule,
    )
    assert record.receivable_dividends == 0
    assert record.net_asset_value == Decimal("2000")
    account.place_order(
        HistoricalOrder(
            "sell-after-record",
            "sh600000",
            Side.SELL,
            Decimal("100"),
            record_date,
            ex_date,
        )
    )
    ex = account.run_day(
        ex_date,
        {"sh600000": Decimal("9.5")},
        {"sh600000": Decimal("9.5")},
        costs,
        {"sh600000": (action,)},
        {},
        rule,
    )
    assert ex.cash == Decimal("1950.0")
    assert ex.receivable_dividends == Decimal("50.0")
    assert ex.net_asset_value == Decimal("2000")
    paid = account.run_day(
        payment_date,
        {"sh600000": Decimal("9.5")},
        {"sh600000": Decimal("9.5")},
        costs,
        {"sh600000": (action,)},
        {},
        rule,
    )
    assert paid.cash == Decimal("2000.0")
    assert paid.receivable_dividends == 0
    assert paid.net_asset_value == Decimal("2000")
    assert [event["event_type"] for event in account.events].count("dividend_accrual") == 1
