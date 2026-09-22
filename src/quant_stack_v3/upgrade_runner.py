"""Corrected historical execution for the bounded CN research upgrade."""

from __future__ import annotations

import json
import math
from collections import Counter
from dataclasses import asdict, dataclass
from datetime import date
from decimal import Decimal
from hashlib import sha256
from pathlib import Path

import numpy as np
import pandas as pd

from quant_stack.costs import CostModel
from quant_stack.data.models import CorporateActionEvent
from quant_stack.evaluation import ExecutionStatistics, evaluate_equity_curve
from quant_stack.models import Side
from quant_stack.paper_models import PaperExecutionRule
from quant_stack.research_json import canonical_json
from quant_stack.snapshot import write_immutable
from quant_stack_v3.actions import (
    PositionTransfer,
    load_actions,
    load_no_participation_overrides,
    unexplained_factor_events,
)
from quant_stack_v3.fast_engine import HistoricalAccount, HistoricalOrder, HistoricalSnapshot
from quant_stack_v3.protocol import Protocol
from quant_stack_v3.upgrade_diagnostics import summarize_turnover_costs
from quant_stack_v3.upgrade_portfolio import (
    PortfolioPolicy,
    apply_weight_policy,
    policy_for,
    select_portfolio,
)


@dataclass(frozen=True)
class UpgradeRunSpec:
    """One fully expanded preregistered executable experiment."""

    experiment_id: str
    strategy_id: str
    scenario_id: str
    initial_cash: Decimal
    execution_delay_sessions: int
    cost_mode: str


@dataclass(frozen=True)
class UpgradeInputs:
    """Immutable identities and locations shared by every upgrade run."""

    bundle_root: Path
    bundle_sha256: str
    bars_path: Path
    scores_path: Path
    artifact_root: Path
    protocol_path: Path
    action_overrides_path: Path


@dataclass(frozen=True)
class PreparedUpgradeData:
    """Read-only in-memory inputs shared across the bounded experiment matrix."""

    sessions: tuple[date, ...]
    bars: pd.DataFrame
    daily_scores: dict[date, pd.DataFrame]
    actions: dict[date, dict[str, tuple[CorporateActionEvent, ...]]]
    transfers: dict[date, tuple[PositionTransfer, ...]]
    unexplained: dict[date, tuple[str, ...]]


def run_upgrade_strategy(
    base_protocol: Protocol,
    spec: UpgradeRunSpec,
    inputs: UpgradeInputs,
) -> tuple[Path, dict[str, object]]:
    """Run one corrected strategy with content-addressed, auditable outputs."""
    if spec.execution_delay_sessions not in {1, 2}:
        raise ValueError("upgrade execution delay exceeds the frozen budget")
    if spec.cost_mode not in {"real", "double_assumption", "zero_all"}:
        raise ValueError("upgrade cost mode is not preregistered")
    policy = policy_for(spec.strategy_id)
    identities = _identities(spec, inputs)
    run_identity = sha256(canonical_json(identities)).hexdigest()
    run_root = inputs.artifact_root / "runs" / run_identity
    result_path = run_root / "result.json"
    if result_path.exists():
        return result_path, json.loads(result_path.read_text(encoding="utf-8"))
    if run_root.exists() and any(run_root.iterdir()):
        raise ValueError("incomplete upgrade run directory already exists")
    run_root.mkdir(parents=True, exist_ok=True)
    prepared = prepare_upgrade_data(base_protocol, inputs)
    return _run_loaded(
        base_protocol,
        spec,
        policy,
        inputs,
        identities,
        run_identity,
        run_root,
        result_path,
        prepared,
    )


def run_upgrade_registry(
    base_protocol: Protocol,
    specs: tuple[UpgradeRunSpec, ...],
    inputs: UpgradeInputs,
) -> dict[str, dict[str, object]]:
    """Execute the exact registry while sharing immutable in-memory inputs."""
    prepared = prepare_upgrade_data(base_protocol, inputs)
    results: dict[str, dict[str, object]] = {}
    for spec in specs:
        if spec.execution_delay_sessions not in {1, 2} or spec.cost_mode not in {
            "real",
            "double_assumption",
            "zero_all",
        }:
            raise ValueError("registry contains an unsupported execution scenario")
        identities = _identities(spec, inputs)
        run_identity = sha256(canonical_json(identities)).hexdigest()
        run_root = inputs.artifact_root / "runs" / run_identity
        result_path = run_root / "result.json"
        if result_path.exists():
            result = json.loads(result_path.read_text(encoding="utf-8"))
        else:
            if run_root.exists() and any(run_root.iterdir()):
                raise ValueError("incomplete upgrade run directory already exists")
            run_root.mkdir(parents=True, exist_ok=True)
            _, result = _run_loaded(
                base_protocol,
                spec,
                policy_for(spec.strategy_id),
                inputs,
                identities,
                run_identity,
                run_root,
                result_path,
                prepared,
            )
        results[spec.experiment_id] = result
    return results


def _identities(spec: UpgradeRunSpec, inputs: UpgradeInputs) -> dict[str, object]:
    return {
        "upgrade_protocol_sha256": _file_sha256(inputs.protocol_path),
        "bundle_sha256": inputs.bundle_sha256,
        "bars_sha256": _file_sha256(inputs.bars_path),
        "scores_sha256": _file_sha256(inputs.scores_path),
        "runner_sha256": _file_sha256(Path(__file__)),
        "engine_sha256": _file_sha256(Path(__file__).with_name("fast_engine.py")),
        "portfolio_sha256": _file_sha256(Path(__file__).with_name("upgrade_portfolio.py")),
        "action_overrides_sha256": _file_sha256(inputs.action_overrides_path),
        "experiment": asdict(spec),
    }


def prepare_upgrade_data(base_protocol: Protocol, inputs: UpgradeInputs) -> PreparedUpgradeData:
    """Load bars, scores and actions once for reuse by all registered runs."""
    sessions = _sessions(
        inputs.bundle_root, base_protocol.research.start, base_protocol.research.end
    )
    bars = pd.read_parquet(inputs.bars_path)
    bars = (
        bars.loc[
            (bars.session >= pd.Timestamp(sessions[0]))
            & (bars.session <= pd.Timestamp(sessions[-1]))
        ]
        .set_index(["session", "symbol"], drop=False)
        .sort_index()
    )
    scores = pd.read_parquet(inputs.scores_path)
    daily_scores = {
        date.fromisoformat(str(session)[:10]): frame.copy()
        for session, frame in scores.groupby("session", sort=True)
    }
    actions, transfers_raw = load_actions(
        inputs.bundle_root,
        bundle_sha256=inputs.bundle_sha256,
        start=sessions[0],
        end=sessions[-1],
    )
    unexplained = unexplained_factor_events(
        inputs.bundle_root, actions, start=sessions[0], end=sessions[-1]
    )
    no_participation = load_no_participation_overrides(inputs.action_overrides_path)
    unexplained = {
        session: tuple(symbol for symbol in symbols if (symbol, session) not in no_participation)
        for session, symbols in unexplained.items()
    }
    transfers: dict[date, tuple[PositionTransfer, ...]] = {
        session: tuple(values) for session, values in transfers_raw.items()
    }
    return PreparedUpgradeData(sessions, bars, daily_scores, actions, transfers, unexplained)


def _run_loaded(
    base_protocol: Protocol,
    spec: UpgradeRunSpec,
    policy: PortfolioPolicy,
    inputs: UpgradeInputs,
    identities: dict[str, object],
    run_identity: str,
    run_root: Path,
    result_path: Path,
    prepared: PreparedUpgradeData,
) -> tuple[Path, dict[str, object]]:
    sessions = prepared.sessions
    bars = prepared.bars
    daily_scores = prepared.daily_scores
    actions = prepared.actions
    transfers = prepared.transfers
    unexplained = prepared.unexplained
    account = HistoricalAccount(f"upgrade-{run_identity}", spec.initial_cash)
    order_intents: list[dict[str, object]] = []
    rebalance_count = 0
    selection_failures: list[str] = []
    warmup_skips = 0
    signal_started = False
    last_signal_ordinal: int | None = None
    for ordinal, session in enumerate(sessions):
        for transfer in transfers.get(session, ()):
            account.transfer_position(
                sha256(
                    f"{run_identity}:{session}:transfer:{transfer.predecessor}:{transfer.successor}".encode()
                ).hexdigest(),
                session,
                transfer.predecessor,
                transfer.successor,
                transfer.ratio,
            )
        today = _daily_rows(bars, session)
        held = {symbol for symbol, quantity in account.positions.items() if quantity > 0}
        due = {order.symbol for order in account.orders if order.execution_date == session}
        needed = held | due
        available = today.loc[today.index.intersection(sorted(needed))]
        raw_opens = {
            str(symbol): Decimal(str(row.raw_open)) for symbol, row in available.iterrows()
        }
        raw_closes = {
            str(symbol): Decimal(str(row.raw_close)) for symbol, row in available.iterrows()
        }
        missing = held - set(raw_closes)
        if missing:
            raise ValueError(
                f"unexplained held valuation missing on {session}: {', '.join(sorted(missing))}"
            )
        unresolved = set(unexplained.get(session, ())) & held
        if unresolved:
            raise ValueError(
                "held position has unexplained action on "
                f"{session}: {', '.join(sorted(unresolved))}"
            )
        blocks = _execution_blocks(account, today, session, actions.get(session, {}))
        rules = {str(symbol): _execution_rule(str(row.board)) for symbol, row in today.iterrows()}
        snapshot = account.run_day(
            session,
            raw_opens,
            raw_closes,
            _costs(base_protocol, session, spec.cost_mode),
            actions.get(session, {}),
            blocks,
            rules,
        )
        if (
            last_signal_ordinal is not None
            and ordinal - last_signal_ordinal < policy.rebalance_sessions
        ):
            continue
        daily = daily_scores.get(session)
        if daily is None:
            selection_failures.append(f"{session}:missing_scores")
            continue
        try:
            decision = select_portfolio(
                daily,
                frozenset(
                    symbol for symbol, quantity in snapshot.positions.items() if quantity > 0
                ),
                policy,
            )
        except ValueError as error:
            if policy.rank_column not in {"score_rank", "liquidity_rank"} and not signal_started:
                warmup_skips += 1
                continue
            selection_failures.append(f"{session}:{error}")
            continue
        signal_started = True
        last_signal_ordinal = ordinal
        execution_index = ordinal + spec.execution_delay_sessions
        if execution_index >= len(sessions):
            continue
        rebalance_count += 1
        records = _place_orders(
            account,
            snapshot,
            decision.symbols,
            decision.weights,
            policy,
            daily,
            today,
            sessions[execution_index],
            run_identity,
        )
        order_intents.extend(records)
    if selection_failures:
        raise ValueError(
            "upgrade signal was not evaluable on preregistered dates: "
            + "; ".join(selection_failures[:5])
        )
    reconciliation = account.reconcile()
    snapshots = tuple(account.snapshots)
    fills = tuple(account.fills)
    equity = pd.Series(
        [float(item.net_asset_value) for item in snapshots],
        index=pd.DatetimeIndex([item.as_of_date for item in snapshots]),
        dtype=float,
    )
    turnover = summarize_turnover_costs(fills, snapshots, spec.initial_cash)
    cash_weights = [
        float(item.cash / item.net_asset_value) for item in snapshots if item.net_asset_value > 0
    ]
    execution = ExecutionStatistics(
        turnover=float(turnover.total.two_sided_turnover),
        total_transaction_costs=float(turnover.total.total_cost),
        rebalances=rebalance_count,
        time_in_market=sum(any(q > 0 for q in item.positions.values()) for item in snapshots)
        / len(snapshots),
        mean_cash_allocation=float(np.mean(cash_weights)),
        maximum_cash_allocation=float(max(cash_weights)),
    )
    metrics = evaluate_equity_curve(equity, execution)
    nav_path = run_root / "nav.parquet"
    pd.DataFrame(
        {
            "session": [item.as_of_date for item in snapshots],
            "nav": [str(item.net_asset_value) for item in snapshots],
            "cash": [str(item.cash) for item in snapshots],
            "receivable": [str(item.receivable_dividends) for item in snapshots],
            "position_count": [sum(q > 0 for q in item.positions.values()) for item in snapshots],
        }
    ).to_parquet(nav_path, index=False, compression="zstd")
    ledger_path = run_root / "ledger.parquet"
    pd.DataFrame(account.events).to_parquet(ledger_path, index=False, compression="zstd")
    intents_path = run_root / "order_intents.parquet"
    pd.DataFrame(order_intents).to_parquet(intents_path, index=False, compression="zstd")
    turnover_path = run_root / "daily_turnover.parquet"
    pd.DataFrame(asdict(item) for item in turnover.daily).to_parquet(
        turnover_path, index=False, compression="zstd"
    )
    turnover_summary = {
        "annualization_sessions": turnover.annualization_sessions,
        "initial_nav": turnover.initial_nav,
        "total": asdict(turnover.total),
        "yearly": {key: asdict(value) for key, value in turnover.yearly.items()},
        "legacy_gross_notional_over_mean_close_nav": (
            turnover.legacy_gross_notional_over_mean_close_nav
        ),
    }
    report: dict[str, object] = {
        "schema_version": 1,
        "run_identity": run_identity,
        "experiment_id": spec.experiment_id,
        "strategy_id": spec.strategy_id,
        "scenario_id": spec.scenario_id,
        "IMPLEMENTATION_STATUS": "IMPLEMENTED_CORRECTED_REAL_DATA_PATH",
        "HISTORICAL_RUN_STATUS": "COMPLETE_REAL_DATA",
        "DATA_USE_LEVEL": "RQALPHA_SINGLE_SOURCE_NONCOMMERCIAL_PRIVATE_RESEARCH_ONLY",
        "RESEARCH_VALIDITY": "VALID_RETROSPECTIVE_FULLY_TOUCHED_COMPARISON",
        "metrics": _json_numbers(asdict(metrics)),
        "calendar_year_returns": _calendar_year_returns(equity, float(spec.initial_cash)),
        "turnover_costs": turnover_summary,
        "execution": {
            "orders": len(account.orders),
            "fills": len(fills),
            "rejections": len(account.rejections),
            "rejection_reasons": dict(
                sorted(Counter(item.reason for item in account.rejections).items())
            ),
            "rebalances": rebalance_count,
            "leading_signal_warmup_skips": warmup_skips,
        },
        "identities": identities
        | {
            "ledger_head": reconciliation.head_hash,
            "ledger_sha256": _file_sha256(ledger_path),
            "nav_sha256": _file_sha256(nav_path),
            "order_intents_sha256": _file_sha256(intents_path),
            "daily_turnover_sha256": _file_sha256(turnover_path),
        },
        "limitations": [
            "final-revised single-vendor history; not strict PIT evidence",
            "fully touched retrospective research; not an untouched holdout",
            "no PIT industry, shares outstanding, or market capitalization input",
        ],
    }
    write_immutable(result_path, canonical_json(report) + b"\n")
    return result_path, report


def _place_orders(
    account: HistoricalAccount,
    snapshot: HistoricalSnapshot,
    symbols: tuple[str, ...],
    weights: dict[str, Decimal],
    policy: PortfolioPolicy,
    daily_scores: pd.DataFrame,
    today: pd.DataFrame,
    execution_date: date,
    run_identity: str,
) -> list[dict[str, object]]:
    nav = snapshot.net_asset_value
    positions = dict(snapshot.positions)
    rows = daily_scores.set_index("symbol", drop=False)
    desired: dict[str, Decimal] = {}
    for symbol in symbols:
        if symbol not in today.index or symbol not in rows.index:
            continue
        row = today.loc[symbol]
        price = Decimal(str(row.raw_close))
        score_row = rows.loc[symbol]
        cap = Decimal(str(score_row.mean_amount_20)) * Decimal("0.01")
        notional = min(nav * weights[symbol], cap)
        full_target = _lot_quantity(notional / price, _execution_rule(str(row.board)))
        current = positions.get(symbol, Decimal("0"))
        current_weight = current * price / nav if nav > 0 else Decimal("0")
        intermediate = apply_weight_policy(
            current_quantity=current,
            target_quantity=full_target,
            current_weight=current_weight,
            target_weight=weights[symbol],
            policy=policy,
        )
        if intermediate >= current:
            intermediate = _lot_quantity(intermediate, _execution_rule(str(row.board)))
        desired[symbol] = max(intermediate, Decimal("0"))
    records: list[dict[str, object]] = []
    rank_symbols = set(str(value) for value in daily_scores["symbol"])
    for symbol in sorted(set(positions) | set(desired)):
        current = positions.get(symbol, Decimal("0"))
        target = desired.get(symbol, Decimal("0"))
        if policy.step_fraction < 1 and target == 0 and current > 0:
            target = current * (Decimal("1") - policy.step_fraction)
            if symbol in today.index:
                rule = _execution_rule(str(today.loc[symbol].board))
                if target < rule.minimum_buy_quantity:
                    target = Decimal("0")
        delta = target - current
        if delta == 0:
            continue
        side, quantity = (Side.BUY, delta) if delta > 0 else (Side.SELL, -delta)
        intent = (
            "entry"
            if current == 0
            else "universe_exit"
            if symbol not in rank_symbols and target == 0
            else "ranking_exit"
            if target == 0
            else "gradual_adjustment"
            if policy.step_fraction < 1
            else "weight_rebalance"
        )
        order_id = sha256(
            f"{run_identity}:{snapshot.as_of_date}:{symbol}:{side.value}:{quantity}".encode()
        ).hexdigest()
        account.place_order(
            HistoricalOrder(
                order_id,
                symbol,
                side,
                quantity,
                snapshot.as_of_date,
                execution_date,
            )
        )
        records.append(
            {
                "order_id": order_id,
                "signal_date": snapshot.as_of_date,
                "execution_date": execution_date,
                "symbol": symbol,
                "side": side.value,
                "quantity": str(quantity),
                "intent": intent,
            }
        )
    return records


def _execution_blocks(
    account: HistoricalAccount,
    today: pd.DataFrame,
    session: date,
    actions: dict[str, tuple[CorporateActionEvent, ...]],
) -> dict[str, str]:
    blocks: dict[str, str] = {}
    for order in account.orders:
        if order.execution_date != session:
            continue
        symbol = order.symbol
        if symbol in actions and any(item.effective_date == session for item in actions[symbol]):
            blocks[symbol] = "corporate_action_execution_day"
        elif symbol not in today.index:
            blocks[symbol] = "missing_open_or_suspended"
        else:
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


def _costs(protocol: Protocol, session: date, mode: str) -> CostModel:
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
        return CostModel(*(Decimal("0") for _ in range(6)))
    multiplier = Decimal("2") if mode == "double_assumption" else Decimal("1")
    return CostModel(
        protocol.costs.commission_rate * multiplier,
        protocol.costs.minimum_commission * multiplier,
        protocol.costs.half_spread_rate * multiplier,
        protocol.costs.slippage_rate * multiplier,
        tax,
        transfer,
    )


def _sessions(bundle_root: Path, start: date, end: date) -> tuple[date, ...]:
    values = np.load(bundle_root / "trading_dates.npy", allow_pickle=False)
    result = tuple(_date_int(item) for item in values)
    selected = tuple(item for item in result if start <= item <= end)
    if not selected or selected[0] != start or selected[-1] != end:
        raise ValueError("upgrade range is not fully present in the calendar")
    return selected


def _daily_rows(bars: pd.DataFrame, session: date) -> pd.DataFrame:
    try:
        rows = bars.loc[pd.Timestamp(session)]
    except KeyError:
        return pd.DataFrame(columns=bars.columns).set_index(pd.Index([], name="symbol"))
    if isinstance(rows, pd.Series):
        rows = rows.to_frame().T
    return rows.set_index("symbol", drop=False)


def _execution_rule(board: str) -> PaperExecutionRule:
    if board == "star":
        return PaperExecutionRule(Decimal("200"), Decimal("1"))
    return PaperExecutionRule(Decimal("100"), Decimal("100"))


def _lot_quantity(quantity: Decimal, rule: PaperExecutionRule) -> Decimal:
    if quantity < rule.minimum_buy_quantity:
        return Decimal("0")
    return (
        rule.minimum_buy_quantity
        + ((quantity - rule.minimum_buy_quantity) // rule.buy_increment) * rule.buy_increment
    )


def _calendar_year_returns(equity: pd.Series, initial_cash: float) -> dict[str, float]:
    output: dict[str, float] = {}
    prior = initial_cash
    years = pd.DatetimeIndex(equity.index).year
    for year, values in equity.groupby(years, sort=True):
        output[str(year)] = float(values.iloc[-1] / prior - 1.0)
        prior = float(values.iloc[-1])
    return output


def _date_int(value: object) -> date:
    integer = int(str(value))
    if integer > 99_999_999:
        integer //= 1_000_000
    text = f"{integer:08d}"
    return date(int(text[:4]), int(text[4:6]), int(text[6:]))


def _json_numbers(values: dict[str, object]) -> dict[str, object]:
    return {
        key: None if isinstance(value, float) and not math.isfinite(value) else value
        for key, value in values.items()
    }


def _file_sha256(path: Path) -> str:
    digest = sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()
