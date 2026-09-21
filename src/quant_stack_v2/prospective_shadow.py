"""Forward-only CSI300 shadow signals and a local paper account."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, date, datetime
from decimal import ROUND_FLOOR, Decimal
from hashlib import sha256
from pathlib import Path
from typing import cast

import pandas as pd
import yaml

from quant_stack.costs import CostModel
from quant_stack.data.calendar import ExchangeCalendarStore
from quant_stack.data.models import CorporateActionEvent, CorporateActionKind, OfficialEvidence
from quant_stack.models import Exchange, Side
from quant_stack.paper_broker import PaperBroker
from quant_stack.paper_models import PaperBrokerConfig, PaperExecutionRule, PaperOrder
from quant_stack.snapshot import write_immutable

ALPHAS = (
    "CN_REV_001",
    "CN_REV_003",
    "CN_PV_003",
    "CN_RANGE_001",
    "CN_VOL_003",
    "CN_VOL_002",
    "CN_PV_004",
)
RAW_FIELDS = (
    "symbol",
    "open",
    "high",
    "low",
    "close",
    "volume",
    "amount",
    "member",
    "st",
    "suspended",
    "exchange",
    "board",
)


class ProspectiveShadowError(ValueError):
    """Raised when a prospective input cannot safely form a signal."""


@dataclass(frozen=True)
class ShadowConfig:
    """Frozen AF-003 prospective settings and evaluation thresholds."""

    strategy_id: str
    selection_count: int
    lot_size: int
    initial_cash: Decimal
    costs: CostModel
    maximum_lookback_sessions: int
    minimum_cross_section: int
    minimum_mean_amount_20d: Decimal
    minimum_fully_prospective_days: int
    minimum_evaluation_coverage: float
    minimum_direction_consistency: float


def load_config(path: Path) -> ShadowConfig:
    """Load the prospective contract while rejecting AF-003 strategy drift."""
    value = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict) or tuple(value.get("selected_alpha_ids", ())) != ALPHAS:
        raise ProspectiveShadowError("must retain the frozen seven AF-003 factors")
    if value.get("selected_model") != "equal_weight_zscore":
        raise ProspectiveShadowError("must retain equal_weight_zscore")
    if value.get("forbidden_uses") != [
        "historical_qualification",
        "bt_001",
        "csi500",
        "live_order",
    ]:
        raise ProspectiveShadowError("forbidden-use boundary changed")
    cost = _mapping(value, "cost_assumption")
    evaluation = _mapping(value, "evaluation")
    costs = CostModel(
        Decimal(str(cost["commission_rate"])),
        Decimal(str(cost["minimum_commission"])),
        Decimal(str(cost["half_spread_rate"])),
        Decimal(str(cost["slippage_rate"])),
        Decimal(str(cost["sell_tax_rate"])),
        Decimal(str(cost["transfer_fee_rate"])),
    )
    return ShadowConfig(
        str(value["strategy_id"]),
        int(value["selection_count"]),
        int(value["lot_size"]),
        Decimal(str(value["initial_cash"])),
        costs,
        int(value["maximum_lookback_sessions"]),
        int(value["minimum_cross_section"]),
        Decimal(str(value["minimum_mean_amount_20d"])),
        int(str(evaluation["minimum_fully_prospective_days"])),
        float(str(evaluation["minimum_evaluation_coverage"])),
        float(str(evaluation["minimum_direction_consistency"])),
    )


def archive_snapshot_payload(payload: dict[str, object], data_root: Path, *, provider: str) -> Path:
    """Content-address one normalized session payload and its provenance receipt."""
    _records(payload)
    session = _session(payload)
    captured = _captured(payload)
    content = _json(payload)
    digest = sha256(content).hexdigest()
    snapshot = data_root / "raw" / digest / "snapshot.json"
    write_immutable(snapshot, content)
    manifest = {
        "schema_version": 1,
        "snapshot_id": digest,
        "source": provider,
        "created_at": captured.isoformat(),
        "files": [{"relative_path": "snapshot.json", "sha256": digest, "size_bytes": len(content)}],
    }
    write_immutable(snapshot.parent / "manifest.json", _json(manifest))
    receipt = {
        "schema_version": 1,
        "INPUT_STATUS": "IMMUTABLE_CURRENT_SNAPSHOT",
        "provider": provider,
        "snapshot_id": digest,
        "snapshot_path": str(snapshot.resolve()),
        "trading_date": session.isoformat(),
        "captured_at": captured.isoformat(),
    }
    receipt_content = _json(receipt)
    path = data_root / "receipts" / f"{sha256(receipt_content).hexdigest()}.json"
    write_immutable(path, receipt_content)
    return path


def archive_current_snapshot(source: Path, data_root: Path, *, provider: str) -> Path:
    """Archive a normalized local JSON snapshot without a network request."""
    return archive_snapshot_payload(_payload(source), data_root, provider=provider)


def build_signal(config: ShadowConfig, receipt: Path, artifact_root: Path) -> Path:
    """Compute a T-close ranking from snapshots captured no later than T's run."""
    identity = _payload(receipt)
    payload = _payload(Path(str(identity["snapshot_path"])))
    session = _session(payload)
    history = _history(receipt.parent.parent, session)
    score = _score(history, session, config)
    top = score.head(config.selection_count)
    input_status = _input_status(history, tuple(top.symbol), session, config)
    result = {
        "schema_version": 2,
        "strategy_id": config.strategy_id,
        "trading_date": session.isoformat(),
        "ENGINEERING_STATUS": "SIGNAL_STAGE_COMPLETE",
        "INPUT_STATUS": input_status,
        "SHADOW_SIGNAL_STATUS": "SIGNAL_EMITTED"
        if len(top) == config.selection_count
        else "INSUFFICIENT_LOOKBACK",
        "PAPER_ACCOUNT_STATUS": "NOT_RUN",
        "PROFITABILITY_STATUS": "INSUFFICIENT_PROSPECTIVE_EVIDENCE",
        "execution_not_before": "next exchange session open",
        "receipt_sha256": receipt.stem,
        "coverage": len(score),
        "scores": score[["symbol", "score"]].to_dict(orient="records") if len(score) else [],
        "top": top[["symbol", "score"]].to_dict(orient="records") if len(top) else [],
    }
    content = _json(result)
    path = artifact_root / "signals" / f"{session.isoformat()}-{sha256(content).hexdigest()}.json"
    write_immutable(path, content)
    return path


def run_paper_day(
    config: ShadowConfig,
    receipt: Path,
    artifact_root: Path,
    *,
    calendar_root: Path = Path("configs/calendars"),
    rules_path: Path = Path("configs/v2/prospective/cn_shadow_rules_v1.yaml"),
) -> Path:
    """Fill prior day-only paper orders at T open and create next-session targets."""
    identity = _payload(receipt)
    payload = _payload(Path(str(identity["snapshot_path"])))
    session = _session(payload)
    history = _history(receipt.parent.parent, session)
    today = history.loc[history["session"] == pd.Timestamp(session)]
    opens = {str(row.symbol): Decimal(str(row.open)) for row in today.itertuples()}
    closes = {str(row.symbol): Decimal(str(row.close)) for row in today.itertuples()}
    broker = PaperBroker(
        artifact_root / "paper" / "strategy.sqlite3",
        PaperBrokerConfig(config.strategy_id, config.costs, config.initial_cash),
    )
    initial = broker.initialize()
    unknown_actions = (
        set(
            cast(
                list[str],
                today.loc[today.action_status == "unknown", "symbol"].tolist(),
            )
        )
        if "action_status" in today.columns
        else set()
    )
    if unknown_actions & set(initial.positions):
        raise ProspectiveShadowError("held position has unresolved corporate-action status")
    rules = _execution_rules(today, rules_path)
    blocks = _execution_blocks(today, broker.orders(), session)
    snapshot = broker.run_daily(
        sha256(f"{config.strategy_id}/{session}/{receipt.stem}".encode()).hexdigest(),
        session,
        opens,
        closes,
        receipt.stem,
        _paper_actions(payload, session),
        execution_block_reasons=blocks,
        execution_rules=rules,
    )
    score = _score(history, session, config).head(config.selection_count)
    if len(score) == config.selection_count:
        desired = _desired_positions(score, today, closes, snapshot.net_asset_value, config, rules)
        calendar = ExchangeCalendarStore(calendar_root)
        sse_next = calendar.next_session(Exchange.SSE, session)
        szse_next = calendar.next_session(Exchange.SZSE, session)
        if sse_next != szse_next:
            raise ProspectiveShadowError("SSE and SZSE next sessions differ")
        for symbol in sorted(set(snapshot.positions) | set(desired)):
            delta = desired.get(symbol, Decimal("0")) - snapshot.positions.get(symbol, Decimal("0"))
            if delta == 0:
                continue
            side, quantity = (Side.BUY, delta) if delta > 0 else (Side.SELL, -delta)
            if side is Side.BUY:
                rule = rules[symbol]
                if quantity < rule.minimum_buy_quantity:
                    continue
                quantity = (
                    rule.minimum_buy_quantity
                    + ((quantity - rule.minimum_buy_quantity) // rule.buy_increment)
                    * rule.buy_increment
                )
            broker.place_order(
                PaperOrder(
                    sha256(
                        f"{config.strategy_id}/{session}/{symbol}/{side.value}/{quantity}".encode()
                    ).hexdigest(),
                    symbol,
                    side,
                    quantity,
                    session,
                    sse_next,
                )
            )
    input_status = _input_status(history, tuple(score.symbol), session, config)
    report = {
        "schema_version": 2,
        "trading_date": session.isoformat(),
        "ENGINEERING_STATUS": "DAILY_RUN_COMPLETE",
        "INPUT_STATUS": input_status,
        "SHADOW_SIGNAL_STATUS": "SIGNAL_EMITTED"
        if len(score) == config.selection_count
        else "INSUFFICIENT_LOOKBACK",
        "PAPER_ACCOUNT_STATUS": "RECONCILED_LOCAL_ONLY",
        "PROFITABILITY_STATUS": "INSUFFICIENT_PROSPECTIVE_EVIDENCE",
        "nav": str(snapshot.net_asset_value),
        "cash": str(snapshot.cash),
        "positions": {key: str(value) for key, value in snapshot.positions.items()},
        "fills_today": sum(item.trading_date == session for item in broker.fills()),
        "rejections_today": [
            item.reason for item in broker.rejections() if item.trading_date == session
        ],
        "ledger_head": broker.reconcile().head_hash,
        "receipt_sha256": receipt.stem,
        "rules_sha256": sha256(rules_path.read_bytes()).hexdigest(),
        "calendar_sha256": ExchangeCalendarStore(calendar_root).fingerprint(
            Exchange.SSE, session, session
        ),
    }
    content = _json(report)
    path = artifact_root / "reports" / f"{session.isoformat()}-{sha256(content).hexdigest()}.json"
    write_immutable(path, content)
    return path


def _history(data_root: Path, through: date) -> pd.DataFrame:
    selected: dict[date, tuple[datetime, dict[str, object]]] = {}
    for manifest in sorted((data_root / "raw").glob("*/manifest.json")):
        meta = _payload(manifest)
        files = meta.get("files")
        if not isinstance(files, list) or not files or not isinstance(files[0], dict):
            raise ProspectiveShadowError("raw snapshot manifest lacks its source file")
        payload = _payload(manifest.parent / str(files[0]["relative_path"]))
        session = _session(payload)
        captured = _captured(payload)
        if session <= through and (session not in selected or captured < selected[session][0]):
            selected[session] = (captured, payload)
    rows: list[dict[str, object]] = []
    for session, (_, payload) in sorted(selected.items()):
        actions = _actions_on(payload, session)
        mode = str(payload.get("observation_mode", "WARM_START_NON_FORMAL"))
        for row in _records(payload):
            cash, ratio = actions.get(str(row["symbol"]), (0.0, 1.0))
            rows.append(
                {
                    **row,
                    "session": pd.Timestamp(session),
                    "observation_mode": mode,
                    "cash_per_unit": cash,
                    "split_ratio": ratio,
                }
            )
    frame = pd.DataFrame(rows)
    if frame.empty or frame.duplicated(["session", "symbol"]).any():
        raise ProspectiveShadowError(
            "raw snapshot history is empty or has duplicate session/symbol rows"
        )
    return _continuous_history(frame.sort_values(["symbol", "session"]))


def _continuous_history(frame: pd.DataFrame) -> pd.DataFrame:
    adjusted: list[pd.DataFrame] = []
    for _, source in frame.groupby("symbol", sort=True):
        group = source.sort_values("session").copy()
        previous_raw: float | None = None
        previous_close: float | None = None
        split_scale = 1.0
        values: list[tuple[float, float, float, float, float]] = []
        for row in group.itertuples():
            raw_close = float(str(row.close))
            split = float(str(row.split_ratio))
            cash = float(str(row.cash_per_unit))
            if previous_raw is None or previous_close is None:
                continuous_close = raw_close
            else:
                continuous_close = previous_close * (raw_close * split + cash) / previous_raw
            split_scale *= split
            price_scale = continuous_close / raw_close
            values.append(
                (
                    float(str(row.open)) * price_scale,
                    float(str(row.high)) * price_scale,
                    float(str(row.low)) * price_scale,
                    continuous_close,
                    float(str(row.volume)) / split_scale,
                )
            )
            previous_raw, previous_close = raw_close, continuous_close
        group[["calc_open", "calc_high", "calc_low", "calc_close", "calc_volume"]] = values
        adjusted.append(group)
    return pd.concat(adjusted, ignore_index=True).sort_values(["symbol", "session"])


def _score(history: pd.DataFrame, session: date, config: ShadowConfig) -> pd.DataFrame:
    rows: list[dict[str, object]] = []
    for symbol, raw in history.groupby("symbol", sort=True):
        group = raw.sort_values("session")
        now = group.iloc[-1]
        if (
            now.session.date() != session
            or len(group) < config.maximum_lookback_sessions
            or not bool(now.member)
            or bool(now.st)
            or bool(now.suspended)
            or ("action_status" in now.index and str(now.action_status) != "complete_or_no_event")
        ):
            continue
        close = group.calc_close.astype(float)
        volume = group.calc_volume.astype(float)
        if (
            Decimal(str(group.amount.astype(float).tail(20).mean()))
            < config.minimum_mean_amount_20d
        ):
            continue
        ret = close.pct_change()
        q = ret.abs().tail(20) * volume.tail(20)
        x = pd.Series(range(5), dtype=float)
        fields = {
            "CN_REV_001": -(x.cov(close.tail(5).reset_index(drop=True)) / x.var() / close.iloc[-1]),
            "CN_REV_003": -((ret.tail(5) > 0).mean() - (ret.tail(5) < 0).mean()),
            "CN_PV_003": volume.tail(20).mean() / volume.iloc[-1],
            "CN_RANGE_001": -(
                group.calc_high.astype(float).tail(20).to_numpy().argmax()
                - group.calc_low.astype(float).tail(20).to_numpy().argmin()
            )
            / 20,
            "CN_VOL_003": -q.std() / (q.mean() + 1e-12),
            "CN_VOL_002": -close.tail(60).std() / close.iloc[-1],
            "CN_PV_004": -volume.tail(20).std() / volume.iloc[-1],
        }
        if pd.notna(pd.Series(fields)).all():
            rows.append({"symbol": str(symbol), **fields})
    frame = pd.DataFrame(rows)
    if len(frame) < config.minimum_cross_section:
        return pd.DataFrame(columns=["symbol", "score"])
    standardized = cast(
        pd.DataFrame,
        frame.loc[:, list(ALPHAS)].apply(
            lambda col: (col - col.mean()) / col.std(ddof=0) if col.std(ddof=0) else 0.0
        ),
    )
    frame["score"] = standardized.mean(axis=1)
    return frame.sort_values(["score", "symbol"], ascending=[False, True])


def _input_status(
    history: pd.DataFrame, symbols: tuple[str, ...], session: date, config: ShadowConfig
) -> str:
    if not symbols:
        return "WARM_START_NON_FORMAL"
    modes: list[str] = []
    for symbol in symbols:
        rows = history.loc[
            (history.symbol == symbol) & (history.session <= pd.Timestamp(session))
        ].tail(config.maximum_lookback_sessions)
        if len(rows) < config.maximum_lookback_sessions:
            return "WARM_START_NON_FORMAL"
        modes.extend(cast(list[str], rows.observation_mode.tolist()))
    if all(mode == "PROSPECTIVE" for mode in modes):
        return "FULLY_PROSPECTIVE_INPUT"
    if any(mode == "PROSPECTIVE" for mode in modes):
        return "MIXED_PROSPECTIVE_INPUT"
    return "WARM_START_NON_FORMAL"


def _desired_positions(
    score: pd.DataFrame,
    today: pd.DataFrame,
    closes: dict[str, Decimal],
    nav: Decimal,
    config: ShadowConfig,
    rules: dict[str, PaperExecutionRule],
) -> dict[str, Decimal]:
    boards = {str(row.symbol): str(row.board) for row in today.itertuples()}
    desired: dict[str, Decimal] = {}
    for row in score.itertuples():
        symbol = str(row.symbol)
        raw = nav / Decimal(config.selection_count) / closes[symbol]
        rule = rules[symbol]
        if boards[symbol] == "star":
            quantity = raw.to_integral_value(rounding=ROUND_FLOOR)
            if quantity < rule.minimum_buy_quantity:
                quantity = Decimal("0")
        else:
            quantity = (raw // rule.buy_increment) * rule.buy_increment
        desired[symbol] = quantity
    return desired


def _execution_rules(today: pd.DataFrame, path: Path) -> dict[str, PaperExecutionRule]:
    payload = yaml.safe_load(path.read_text(encoding="utf-8"))
    boards = _mapping(payload, "boards")
    result: dict[str, PaperExecutionRule] = {}
    for row in today.itertuples():
        value = _mapping(boards, str(row.board))
        result[str(row.symbol)] = PaperExecutionRule(
            Decimal(str(value["minimum_buy_quantity"])), Decimal(str(value["buy_increment"]))
        )
    return result


def _execution_blocks(
    today: pd.DataFrame, orders: tuple[PaperOrder, ...], session: date
) -> dict[str, str]:
    pending = {
        order.symbol: order.side for order in orders if order.earliest_execution_date == session
    }
    blocked: dict[str, str] = {}
    for row in today.itertuples():
        symbol = str(row.symbol)
        side = pending.get(symbol)
        if side is None:
            continue
        if bool(row.suspended):
            blocked[symbol] = "suspended"
        elif float(str(row.open)) == float(str(row.high)) == float(str(row.low)):
            if side is Side.BUY and float(str(row.close)) > float(str(row.previous_close)):
                blocked[symbol] = "one_price_up_limit"
            elif side is Side.SELL and float(str(row.close)) < float(str(row.previous_close)):
                blocked[symbol] = "one_price_down_limit"
    return blocked


def _actions_on(payload: dict[str, object], session: date) -> dict[str, tuple[float, float]]:
    actions = payload.get("corporate_actions", [])
    if not isinstance(actions, list):
        raise ProspectiveShadowError("corporate_actions must be a list")
    result: dict[str, tuple[float, float]] = {}
    for action in actions:
        if not isinstance(action, dict) or action.get("effective_date") != session.isoformat():
            continue
        symbol = str(action["symbol"])
        cash, ratio = result.get(symbol, (0.0, 1.0))
        if action["kind"] == "cash_distribution":
            cash += float(action["cash_per_unit"])
        elif action["kind"] == "share_split":
            ratio *= float(action["split_ratio"])
        result[symbol] = (cash, ratio)
    return result


def _paper_actions(
    payload: dict[str, object], session: date
) -> dict[str, tuple[CorporateActionEvent, ...]]:
    raw = payload.get("corporate_actions", [])
    if not isinstance(raw, list):
        raise ProspectiveShadowError("corporate_actions must be a list")
    result: dict[str, list[CorporateActionEvent]] = {}
    for item in raw:
        if not isinstance(item, dict):
            raise ProspectiveShadowError("corporate action must be an object")
        relevant_dates = {
            str(item.get("effective_date", "")),
            str(item.get("record_date", "")),
            str(item.get("payment_date", "")),
        }
        if session.isoformat() not in relevant_dates:
            continue
        published = date.fromisoformat(str(item["announcement_date"]))
        evidence = OfficialEvidence(
            url=str(item["source_url"]), sha256=str(item["source_sha256"]), published_on=published
        )
        kind = CorporateActionKind(str(item["kind"]))
        event = CorporateActionEvent(
            effective_date=date.fromisoformat(str(item["effective_date"])),
            kind=kind,
            cash_per_unit=Decimal(str(item["cash_per_unit"]))
            if kind is CorporateActionKind.CASH_DISTRIBUTION
            else None,
            split_ratio=Decimal(str(item["split_ratio"]))
            if kind is CorporateActionKind.SHARE_SPLIT
            else None,
            evidence=evidence,
            event_announcement_date=published,
            record_date=date.fromisoformat(str(item["record_date"]))
            if item.get("record_date")
            else None,
            payment_date=date.fromisoformat(str(item["payment_date"]))
            if item.get("payment_date")
            else None,
        )
        result.setdefault(str(item["symbol"]), []).append(event)
    return {symbol: tuple(events) for symbol, events in result.items()}


def _records(payload: dict[str, object]) -> list[dict[str, object]]:
    records = payload.get("records")
    if not isinstance(records, list) or not records:
        raise ProspectiveShadowError("snapshot records are required")
    for record in records:
        if not isinstance(record, dict) or not set(RAW_FIELDS) <= set(record):
            raise ProspectiveShadowError("snapshot record lacks required current fields")
        for field in ("open", "high", "low", "close", "volume", "amount", "previous_close"):
            if field not in record or float(record[field]) < 0:
                raise ProspectiveShadowError(f"snapshot record has invalid {field}")
    return cast(list[dict[str, object]], records)


def _payload(path: Path) -> dict[str, object]:
    value = json.loads(path.read_bytes())
    if not isinstance(value, dict):
        raise ProspectiveShadowError(f"JSON object required: {path}")
    return cast(dict[str, object], value)


def _session(payload: dict[str, object]) -> date:
    try:
        return date.fromisoformat(str(payload["trading_date"]))
    except (KeyError, ValueError) as error:
        raise ProspectiveShadowError("trading_date is required") from error


def _captured(payload: dict[str, object]) -> datetime:
    try:
        value = datetime.fromisoformat(str(payload["captured_at"]))
    except (KeyError, ValueError) as error:
        raise ProspectiveShadowError("captured_at is required") from error
    if value.tzinfo is None or value.utcoffset() is None:
        raise ProspectiveShadowError("captured_at must be timezone-aware")
    return value.astimezone(UTC)


def _mapping(value: object, key: str) -> dict[str, object]:
    if not isinstance(value, dict) or not isinstance(value.get(key), dict):
        raise ProspectiveShadowError(f"{key} mapping is required")
    return cast(dict[str, object], value[key])


def _json(value: object) -> bytes:
    return (
        json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
        + b"\n"
    )
