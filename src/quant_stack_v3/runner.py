"""Deterministic real-data V3 execution through the existing local paper ledger."""

from __future__ import annotations

import json
import math
from collections import Counter
from dataclasses import asdict, dataclass
from datetime import UTC, date, datetime, time, timedelta, timezone
from decimal import Decimal
from hashlib import sha256
from pathlib import Path

import numpy as np
import pandas as pd

from quant_stack.costs import CostModel
from quant_stack.data.models import CorporateActionEvent
from quant_stack.evaluation import ExecutionStatistics, evaluate_equity_curve
from quant_stack.models import Side
from quant_stack.paper_broker import PaperBroker
from quant_stack.paper_models import (
    PaperBrokerConfig,
    PaperExecutionRule,
    PaperOrder,
    PaperSnapshot,
)
from quant_stack.research_json import canonical_json
from quant_stack.snapshot import write_immutable
from quant_stack_v3.actions import load_actions
from quant_stack_v3.protocol import Protocol, StrategySpec
from quant_stack_v3.targets import TargetSet, build_targets


@dataclass(frozen=True)
class RunOptions:
    """Mechanical execution variation outside the six main strategy definitions."""

    delay_sessions: int = 1
    friction_multiplier: Decimal = Decimal("1")


def run_strategy(
    protocol: Protocol,
    protocol_path: Path,
    strategy: StrategySpec,
    options: RunOptions,
    *,
    bundle_root: Path,
    bundle_sha256: str,
    bars_path: Path,
    scores_path: Path,
    artifact_root: Path,
) -> tuple[Path, dict[str, object]]:
    """Run one frozen strategy and publish its complete aggregate result."""
    if options.delay_sessions not in {1, 2} or options.friction_multiplier not in {
        Decimal("1"),
        Decimal("2"),
    }:
        raise ValueError("V3 run options exceed the preregistered stress budget")
    bars_sha = _file_sha256(bars_path)
    scores_sha = _file_sha256(scores_path)
    identity_payload = {
        "protocol_sha256": sha256(protocol_path.read_bytes()).hexdigest(),
        "strategy": strategy.model_dump(mode="json"),
        "options": asdict(options),
        "bundle_sha256": bundle_sha256,
        "bars_sha256": bars_sha,
        "scores_sha256": scores_sha,
        "runner_sha256": _file_sha256(Path(__file__)),
        "paper_broker_sha256": _file_sha256(
            Path(__file__).parents[1] / "quant_stack" / "paper_broker.py"
        ),
    }
    run_identity = sha256(canonical_json(identity_payload)).hexdigest()
    run_root = artifact_root / "runs" / run_identity
    result_path = run_root / "result.json"
    if result_path.exists():
        return result_path, json.loads(result_path.read_text(encoding="utf-8"))
    if run_root.exists() and any(run_root.iterdir()):
        raise ValueError("incomplete historical run directory already exists")
    run_root.mkdir(parents=True, exist_ok=True)
    bars = pd.read_parquet(bars_path)
    scores = pd.read_parquet(scores_path)
    sessions = _sessions(bundle_root, protocol.research.start, protocol.research.end)
    targets = {
        item.signal_date: item
        for item in build_targets(
            scores,
            sessions,
            strategy,
            selection_count=protocol.signal.selection_count,
            liquidity_fraction=protocol.execution.maximum_trailing_amount_fraction,
        )
    }
    bars = (
        bars.loc[
            (bars.session >= pd.Timestamp(protocol.research.start))
            & (bars.session <= pd.Timestamp(protocol.research.end))
        ]
        .set_index(["session", "symbol"], drop=False)
        .sort_index()
    )
    actions, transfers = load_actions(
        bundle_root,
        bundle_sha256=bundle_sha256,
        start=protocol.research.start,
        end=protocol.research.end,
    )
    database = run_root / "strategy.sqlite3"
    account_id = f"historical-v3-{run_identity}"
    initial_costs = _costs(protocol, sessions[0], options.friction_multiplier)
    PaperBroker(
        database,
        PaperBrokerConfig(account_id, initial_costs, protocol.execution.initial_cash),
    ).initialize()
    last_closes: dict[str, Decimal] = {}
    stale_counts: dict[str, int] = {}
    maximum_stale = 0
    stale_observations = 0
    index_by_session = {session: index for index, session in enumerate(sessions)}
    for session in sessions:
        broker = PaperBroker(
            database,
            PaperBrokerConfig(
                account_id,
                _costs(protocol, session, options.friction_multiplier),
                protocol.execution.initial_cash,
            ),
        )
        for transfer in transfers.get(session, ()):
            broker.transfer_position(
                sha256(
                    f"{run_identity}:{session}:transfer:{transfer.predecessor}:{transfer.successor}".encode()
                ).hexdigest(),
                session,
                transfer.predecessor,
                transfer.successor,
                transfer.ratio,
            )
        today = _daily_rows(bars, session)
        raw_opens = {str(symbol): Decimal(str(row.raw_open)) for symbol, row in today.iterrows()}
        raw_closes = {str(symbol): Decimal(str(row.raw_close)) for symbol, row in today.iterrows()}
        last_closes.update(raw_closes)
        before = broker.snapshot()
        for symbol, quantity in before.positions.items():
            if quantity <= 0:
                continue
            if symbol in raw_closes:
                stale_counts[symbol] = 0
                continue
            if symbol not in last_closes:
                raise ValueError(f"held position lacks any valuation: {symbol}")
            raw_closes[symbol] = last_closes[symbol]
            stale_counts[symbol] = stale_counts.get(symbol, 0) + 1
            maximum_stale = max(maximum_stale, stale_counts[symbol])
            stale_observations += 1
        blocks = _execution_blocks(broker, today, session, actions.get(session, {}))
        rules = {str(symbol): _execution_rule(str(row.board)) for symbol, row in today.iterrows()}
        snapshot = broker.run_daily(
            sha256(f"{run_identity}:{session}".encode()).hexdigest(),
            session,
            raw_opens,
            raw_closes,
            bars_sha,
            actions.get(session, {}),
            execution_block_reasons=blocks,
            execution_rules=rules,
            generated_at=_generated_at(session),
            is_backfill=True,
        )
        target = targets.get(session)
        if target is not None:
            execution_index = index_by_session[session] + options.delay_sessions
            if execution_index < len(sessions):
                _place_target_orders(
                    broker,
                    snapshot,
                    target,
                    today,
                    sessions[execution_index],
                    run_identity,
                )
    broker = PaperBroker(
        database,
        PaperBrokerConfig(
            account_id,
            _costs(protocol, sessions[-1], options.friction_multiplier),
            protocol.execution.initial_cash,
        ),
    )
    reconciliation = broker.reconcile()
    snapshots = broker.snapshots()
    fills = broker.fills()
    rejections = broker.rejections()
    equity = pd.Series(
        [float(item.net_asset_value) for item in snapshots],
        index=pd.DatetimeIndex([item.as_of_date for item in snapshots]),
        dtype=float,
    )
    costs = sum(
        (
            item.commission
            + item.spread_cost
            + item.slippage_cost
            + item.tax_cost
            + item.transfer_fee
            for item in fills
        ),
        Decimal("0"),
    )
    mean_nav = sum((item.net_asset_value for item in snapshots), Decimal("0")) / Decimal(
        len(snapshots)
    )
    turnover = (
        sum((abs(item.notional) for item in fills), Decimal("0")) / mean_nav
        if mean_nav > 0
        else Decimal("0")
    )
    cash_weights = [
        float(item.cash / item.net_asset_value) for item in snapshots if item.net_asset_value > 0
    ]
    execution = ExecutionStatistics(
        turnover=float(turnover),
        total_transaction_costs=float(costs),
        rebalances=len(targets),
        time_in_market=sum(
            bool([q for q in item.positions.values() if q > 0]) for item in snapshots
        )
        / len(snapshots),
        mean_cash_allocation=float(np.mean(cash_weights)),
        maximum_cash_allocation=float(max(cash_weights)),
    )
    metrics = evaluate_equity_curve(equity, execution)
    nav_frame = pd.DataFrame(
        {
            "session": [item.as_of_date for item in snapshots],
            "nav": [str(item.net_asset_value) for item in snapshots],
            "cash": [str(item.cash) for item in snapshots],
            "position_count": [
                sum(quantity > 0 for quantity in item.positions.values()) for item in snapshots
            ],
        }
    )
    nav_path = run_root / "nav.parquet"
    nav_frame.to_parquet(nav_path, index=False, compression="zstd")
    nav_sha = _file_sha256(nav_path)
    year_index = pd.DatetimeIndex(equity.index).year
    yearly_returns = {
        str(year): _period_return(group) for year, group in equity.groupby(year_index, sort=True)
    }
    validity = (
        "NOT_EVALUABLE_STALE_HELD_VALUATION"
        if maximum_stale > 5
        else "VALID_RETROSPECTIVE_DEVELOPMENT_COMPARISON"
    )
    report: dict[str, object] = {
        "schema_version": 1,
        "run_identity": run_identity,
        "strategy_id": strategy.id,
        "strategy": strategy.model_dump(mode="json"),
        "options": asdict(options),
        "IMPLEMENTATION_STATUS": "IMPLEMENTED_REAL_DATA_PATH",
        "HISTORICAL_RUN_STATUS": "COMPLETE_REAL_DATA",
        "DATA_USE_LEVEL": "RQALPHA_NONCOMMERCIAL_PRIVATE_RESEARCH_ONLY_FINAL_REVISED",
        "RESEARCH_VALIDITY": validity,
        "ECONOMIC_OUTCOME": "PENDING_MATRIX_COMPARISON",
        "PROSPECTIVE_ISOLATION_STATUS": "SEPARATE_WORKTREE_ENV_DATA_AND_LEDGER",
        "sample": {
            "start": sessions[0],
            "end": sessions[-1],
            "sessions": len(sessions),
            "touched_development_end": protocol.research.touched_development_end,
        },
        "metrics": _metric_payload(asdict(metrics)),
        "periods": {
            "calendar_year_returns": yearly_returns,
            "touched_2015_2020_return": _period_return(
                equity.loc[: pd.Timestamp(protocol.research.touched_development_end)]
            ),
            "post_selection_2021_2025_return": _period_return(
                equity.loc[pd.Timestamp(protocol.research.touched_development_end) :].iloc[1:]
            ),
        },
        "execution": {
            "orders": len(broker.orders()),
            "fills": len(fills),
            "rejections": len(rejections),
            "rejection_reasons": dict(sorted(Counter(item.reason for item in rejections).items())),
            "direct_cost_total": costs,
            "direct_cost_fraction_initial_cash": costs / protocol.execution.initial_cash,
            "maximum_stale_sessions": maximum_stale,
            "stale_valuation_observations": stale_observations,
        },
        "identities": identity_payload
        | {
            "ledger_head": reconciliation.head_hash,
            "ledger_events": reconciliation.event_count,
            "nav_sha256": nav_sha,
        },
        "limitations": [
            "final-revised vendor history; not strict point-in-time official evidence",
            "daily open matching with frozen spread/slippage; no intraday queue evidence",
            "dynamic liquidity universe; not historical CSI300",
            "fully touched retrospective research; not an independent holdout",
        ],
    }
    write_immutable(result_path, canonical_json(report) + b"\n")
    return result_path, report


def _sessions(bundle_root: Path, start: date, end: date) -> tuple[date, ...]:
    values = np.load(bundle_root / "trading_dates.npy", allow_pickle=False)
    sessions = tuple(_date_int(item) for item in values)
    selected = tuple(item for item in sessions if start <= item <= end)
    if not selected or selected[0] != start or selected[-1] != end:
        raise ValueError("research range is not fully present in the bundle calendar")
    return selected


def _daily_rows(bars: pd.DataFrame, session: date) -> pd.DataFrame:
    try:
        rows = bars.loc[pd.Timestamp(session)]
    except KeyError:
        return pd.DataFrame(columns=bars.columns).set_index(pd.Index([], name="symbol"))
    if isinstance(rows, pd.Series):
        rows = rows.to_frame().T
    return rows.set_index("symbol", drop=False)


def _execution_blocks(
    broker: PaperBroker,
    today: pd.DataFrame,
    session: date,
    actions: dict[str, tuple[CorporateActionEvent, ...]],
) -> dict[str, str]:
    blocks: dict[str, str] = {}
    for order in broker.orders():
        if order.earliest_execution_date > session:
            continue
        symbol = order.symbol
        if symbol in actions and any(
            getattr(item, "effective_date", None) == session for item in actions[symbol]
        ):
            blocks[symbol] = "corporate_action_execution_day"
            continue
        if symbol not in today.index:
            blocks[symbol] = "missing_open_or_suspended"
            continue
        row = today.loc[symbol]
        if bool(row.suspended):
            blocks[symbol] = "suspended"
        elif (
            order.side is Side.BUY
            and float(row.limit_up) > 0
            and float(row.raw_open) >= float(row.limit_up)
        ):
            blocks[symbol] = "buy_open_at_upper_limit"
        elif (
            order.side is Side.SELL
            and float(row.limit_down) > 0
            and float(row.raw_open) <= float(row.limit_down)
        ):
            blocks[symbol] = "sell_open_at_lower_limit"
    return blocks


def _place_target_orders(
    broker: PaperBroker,
    snapshot: PaperSnapshot,
    target: TargetSet,
    today: pd.DataFrame,
    execution_date: date,
    run_identity: str,
) -> None:
    positions = dict(snapshot.positions)
    desired: dict[str, Decimal] = {}
    for symbol in target.symbols:
        if symbol not in today.index:
            continue
        row = today.loc[symbol]
        price = Decimal(str(row.raw_close))
        notional = min(
            snapshot.net_asset_value * target.weights[symbol], target.maximum_notional[symbol]
        )
        desired[symbol] = _lot_quantity(notional / price, _execution_rule(str(row.board)))
    for symbol in sorted(set(positions) | set(desired)):
        delta = desired.get(symbol, Decimal("0")) - positions.get(symbol, Decimal("0"))
        if delta == 0:
            continue
        side, quantity = (Side.BUY, delta) if delta > 0 else (Side.SELL, -delta)
        order_id = sha256(
            f"{run_identity}:{target.signal_date}:{symbol}:{side.value}:{quantity}".encode()
        ).hexdigest()
        broker.place_order(
            PaperOrder(
                order_id,
                symbol,
                side,
                quantity,
                target.signal_date,
                execution_date,
            )
        )


def _lot_quantity(quantity: Decimal, rule: PaperExecutionRule) -> Decimal:
    if quantity < rule.minimum_buy_quantity:
        return Decimal("0")
    return (
        rule.minimum_buy_quantity
        + ((quantity - rule.minimum_buy_quantity) // rule.buy_increment) * rule.buy_increment
    )


def _execution_rule(board: str) -> PaperExecutionRule:
    if board == "star":
        return PaperExecutionRule(Decimal("200"), Decimal("1"))
    return PaperExecutionRule(Decimal("100"), Decimal("100"))


def _costs(protocol: Protocol, session: date, multiplier: Decimal) -> CostModel:
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
    return CostModel(
        protocol.costs.commission_rate * multiplier,
        protocol.costs.minimum_commission * multiplier,
        protocol.costs.half_spread_rate * multiplier,
        protocol.costs.slippage_rate * multiplier,
        tax,
        transfer,
    )


def _generated_at(session: date) -> datetime:
    shanghai = timezone(timedelta(hours=8))
    return datetime.combine(session, time(16, 0), tzinfo=shanghai).astimezone(UTC)


def _date_int(value: object) -> date:
    integer = int(str(value))
    if integer > 99_999_999:
        integer //= 1_000_000
    text = f"{integer:08d}"
    return date(int(text[:4]), int(text[4:6]), int(text[6:]))


def _file_sha256(path: Path) -> str:
    digest = sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def _metric_payload(values: dict[str, object]) -> dict[str, object]:
    return {
        key: None if isinstance(value, float) and not math.isfinite(value) else value
        for key, value in values.items()
    }


def _period_return(equity: pd.Series) -> float | None:
    if len(equity) < 2 or equity.iloc[0] <= 0:
        return None
    return float(equity.iloc[-1] / equity.iloc[0] - 1.0)
