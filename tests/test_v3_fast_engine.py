"""Independent equivalence checks against the existing PaperBroker accounting."""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from pathlib import Path

from quant_stack.costs import CostModel
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
