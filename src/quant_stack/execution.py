"""Deterministic target-weight simulation with explicit close-signal to later-open fills."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from decimal import Decimal
from typing import cast

import pandas as pd

from quant_stack.costs import CostModel, trade_cost


@dataclass(frozen=True)
class SimulatedTrade:
    """One auditable simulated target-weight trade; no broker interaction is possible."""

    execution_date: pd.Timestamp
    symbol: str
    notional: Decimal
    transaction_cost: Decimal
    raw_fill_price: Decimal
    raw_quantity: Decimal


@dataclass(frozen=True)
class TargetWeightSimulation:
    """Daily marked equity and immutable simulated fill evidence."""

    equity: pd.Series
    cash_weights: pd.Series
    turnover: float
    total_transaction_costs: float
    rebalances: int
    trades: tuple[SimulatedTrade, ...]
    rejected_signal_dates: tuple[pd.Timestamp, ...]


def simulate_target_weights(
    open_prices: pd.DataFrame,
    close_prices: pd.DataFrame,
    targets_by_signal_date: Mapping[pd.Timestamp, Mapping[str, Decimal]],
    cost_model: CostModel,
    execution_delay_sessions: int = 1,
    initial_cash: Decimal = Decimal("100000"),
    execution_audit_prices: pd.DataFrame | None = None,
) -> TargetWeightSimulation:
    """Execute later-open target notionals and retain an explicit raw-price fill audit."""
    _validate_prices(open_prices, close_prices)
    audit_prices = execution_audit_prices if execution_audit_prices is not None else open_prices
    _validate_audit_prices(open_prices, audit_prices)
    if execution_delay_sessions < 1 or initial_cash <= 0:
        raise ValueError("execution delay must be at least one session and initial cash positive")
    index = cast(pd.DatetimeIndex, open_prices.index)
    schedule, rejected = _execution_schedule(
        index, targets_by_signal_date, execution_delay_sessions
    )
    positions = {symbol: Decimal("0") for symbol in open_prices.columns}
    cash = initial_cash
    equity_values: list[Decimal] = []
    cash_weights: list[float] = []
    trades: list[SimulatedTrade] = []
    turnover = Decimal("0")
    rebalances = 0
    for timestamp in open_prices.index:
        if timestamp in schedule:
            target = schedule[timestamp]
            pre_trade_value = cash + _position_value(positions, open_prices.loc[timestamp])
            day_trades, cash, day_turnover = _rebalance(
                timestamp,
                positions,
                open_prices.loc[timestamp],
                cash,
                target,
                pre_trade_value,
                cost_model,
                audit_prices.loc[timestamp],
            )
            trades.extend(day_trades)
            turnover += day_turnover
            rebalances += 1
        close_value = cash + _position_value(positions, close_prices.loc[timestamp])
        equity_values.append(close_value)
        cash_weights.append(float(cash / close_value))
    return TargetWeightSimulation(
        equity=pd.Series([float(value) for value in equity_values], index=close_prices.index),
        cash_weights=pd.Series(cash_weights, index=close_prices.index),
        turnover=float(turnover),
        total_transaction_costs=float(
            sum((trade.transaction_cost for trade in trades), Decimal("0"))
        ),
        rebalances=rebalances,
        trades=tuple(trades),
        rejected_signal_dates=tuple(rejected),
    )


def _execution_schedule(
    index: pd.DatetimeIndex,
    targets: Mapping[pd.Timestamp, Mapping[str, Decimal]],
    delay: int,
) -> tuple[dict[pd.Timestamp, Mapping[str, Decimal]], list[pd.Timestamp]]:
    """Map every signal session to its fixed later execution session without substitution."""
    schedule: dict[pd.Timestamp, Mapping[str, Decimal]] = {}
    rejected: list[pd.Timestamp] = []
    for signal_date, target in targets.items():
        location = index.get_indexer(pd.DatetimeIndex([signal_date]))[0]
        if location < 0:
            raise ValueError("every signal date must be an available exchange session")
        execution_location = location + delay
        if execution_location >= len(index):
            rejected.append(signal_date)
        else:
            schedule[index[execution_location]] = target
    return schedule, rejected


def _rebalance(
    timestamp: pd.Timestamp,
    positions: dict[str, Decimal],
    open_row: pd.Series,
    cash: Decimal,
    target: Mapping[str, Decimal],
    pre_trade_value: Decimal,
    cost_model: CostModel,
    audit_row: pd.Series,
) -> tuple[list[SimulatedTrade], Decimal, Decimal]:
    """Sell before buys, charge every fill, and retain any unaffordable residual as cash."""
    _validate_target(target, tuple(positions))
    trades: list[SimulatedTrade] = []
    turnover = Decimal("0")
    for symbol in sorted(positions):
        price = _decimal_price(open_row[symbol])
        desired = pre_trade_value * target.get(symbol, Decimal("0"))
        current = positions[symbol] * price
        if current > desired:
            notional = current - desired
            cost = trade_cost(notional, cost_model)
            positions[symbol] -= notional / price
            cash += notional - cost
            turnover += notional / pre_trade_value
            raw_price = _decimal_price(audit_row[symbol])
            trades.append(
                SimulatedTrade(timestamp, symbol, -notional, cost, raw_price, -notional / raw_price)
            )
    for symbol in sorted(positions):
        price = _decimal_price(open_row[symbol])
        desired = pre_trade_value * target.get(symbol, Decimal("0"))
        current = positions[symbol] * price
        if desired > current:
            requested_notional = desired - current
            notional = min(requested_notional, _affordable_notional(cash, cost_model))
            if notional == 0:
                continue
            cost = trade_cost(notional, cost_model)
            if notional + cost > cash:
                # Decimal division can round the affordability bound upwards by one ULP.
                notional = notional.next_minus()
                cost = trade_cost(notional, cost_model)
            if notional + cost > cash:
                raise ValueError("affordability calculation produced negative cash")
            positions[symbol] += notional / price
            cash -= notional + cost
            if cash < 0:
                raise ValueError("affordability calculation produced negative cash")
            turnover += notional / pre_trade_value
            raw_price = _decimal_price(audit_row[symbol])
            trades.append(
                SimulatedTrade(timestamp, symbol, notional, cost, raw_price, notional / raw_price)
            )
    return trades, cash, turnover


def _validate_prices(open_prices: pd.DataFrame, close_prices: pd.DataFrame) -> None:
    """Require one complete, aligned, ascending daily panel without synthesized prices."""
    if (
        not open_prices.index.equals(close_prices.index)
        or not open_prices.columns.equals(close_prices.columns)
        or not isinstance(open_prices.index, pd.DatetimeIndex)
        or not open_prices.index.is_monotonic_increasing
        or not open_prices.index.is_unique
        or open_prices.empty
        or open_prices.isna().any().any()
        or close_prices.isna().any().any()
        or (open_prices <= 0).any().any()
        or (close_prices <= 0).any().any()
    ):
        raise ValueError("open and close panels must be complete identical positive daily panels")


def _validate_target(target: Mapping[str, Decimal], symbols: tuple[str, ...]) -> None:
    """Reject short, leveraged, unknown, or non-normalized target portfolios."""
    allowed = set(symbols) | {"CASH"}
    if set(target) - allowed or any(weight < 0 for weight in target.values()):
        raise ValueError("target must contain only known long-only symbols and CASH")
    if sum(target.values(), Decimal("0")) != Decimal("1"):
        raise ValueError("target weights including CASH must sum exactly to one")


def _validate_audit_prices(accounting_open: pd.DataFrame, audit_open: pd.DataFrame) -> None:
    """Require raw execution-audit opens to align exactly with the accounting panel."""
    if (
        not accounting_open.index.equals(audit_open.index)
        or not accounting_open.columns.equals(audit_open.columns)
        or audit_open.isna().any().any()
        or (audit_open <= 0).any().any()
    ):
        raise ValueError("execution audit prices must be aligned complete positive raw opens")


def _position_value(positions: Mapping[str, Decimal], prices: pd.Series) -> Decimal:
    """Value all current long positions at the supplied daily price row."""
    return sum(
        (quantity * _decimal_price(prices[symbol]) for symbol, quantity in positions.items()),
        Decimal("0"),
    )


def _decimal_price(value: object) -> Decimal:
    """Convert one validated price cell without binary-float arithmetic in the ledger."""
    return Decimal(str(value))


def _affordable_notional(cash: Decimal, model: CostModel) -> Decimal:
    """Return the largest buy notional that leaves non-negative cash after frozen costs."""
    variable_rate = model.commission_rate + model.half_spread_rate + model.slippage_rate
    if model.commission_rate == 0:
        return cash / (Decimal("1") + variable_rate)
    if cash <= model.minimum_commission:
        return Decimal("0")
    minimum_commission_boundary = model.minimum_commission / model.commission_rate
    non_commission_rate = model.half_spread_rate + model.slippage_rate
    fixed_commission_notional = (cash - model.minimum_commission) / (
        Decimal("1") + non_commission_rate
    )
    if fixed_commission_notional <= minimum_commission_boundary:
        return fixed_commission_notional
    return cash / (Decimal("1") + variable_rate)
