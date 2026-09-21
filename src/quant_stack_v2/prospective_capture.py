"""Free, bounded provider capture for the prospective CSI300 shadow loop."""

from __future__ import annotations

import importlib
import json
import time
from collections.abc import Callable, Iterable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import UTC, date, datetime
from datetime import time as wall_time
from hashlib import sha256
from pathlib import Path
from typing import cast
from zoneinfo import ZoneInfo

import pandas as pd

from quant_stack.snapshot import write_immutable
from quant_stack_v2.prospective_shadow import archive_snapshot_payload

SHANGHAI = ZoneInfo("Asia/Shanghai")
MembershipQuery = Callable[[], pd.DataFrame]
HistoryQuery = Callable[[str, date, date], pd.DataFrame]
SpotQuery = Callable[[], pd.DataFrame]
ActionQuery = Callable[[str], pd.DataFrame]
BenchmarkQuery = Callable[[], pd.DataFrame]


class ProspectiveCaptureError(ValueError):
    """Raised when a free provider cannot form a valid immutable snapshot."""


@dataclass(frozen=True)
class LiveQueries:
    """Injectable provider calls; tests use fixtures and production uses AKShare."""

    membership: MembershipQuery
    history: HistoryQuery
    spot: SpotQuery
    actions: ActionQuery
    benchmark: BenchmarkQuery
    crosscheck: SpotQuery | None = None


def default_queries() -> LiveQueries:
    """Return the current free provider methods without invoking the network."""
    ak = importlib.import_module("akshare")

    def membership() -> pd.DataFrame:
        return cast(pd.DataFrame, ak.index_stock_cons_csindex(symbol="000300"))

    def history(symbol: str, start: date, end: date) -> pd.DataFrame:
        return cast(
            pd.DataFrame,
            ak.stock_zh_a_hist_tx(
                symbol=symbol,
                start_date=start.strftime("%Y%m%d"),
                end_date=end.strftime("%Y%m%d"),
                adjust="",
                timeout=30,
            ),
        )

    def spot() -> pd.DataFrame:
        return cast(pd.DataFrame, ak.stock_zh_a_spot_tx())

    def actions(symbol: str) -> pd.DataFrame:
        return cast(pd.DataFrame, ak.stock_dividend_cninfo(symbol=symbol[-6:]))

    def benchmark() -> pd.DataFrame:
        return cast(pd.DataFrame, ak.stock_zh_index_daily_tx(symbol="sh000300"))

    def crosscheck() -> pd.DataFrame:
        return cast(pd.DataFrame, ak.stock_zh_a_spot())

    return LiveQueries(membership, history, spot, actions, benchmark, crosscheck)


def source_probe(queries: LiveQueries | None = None) -> dict[str, object]:
    """Probe one bounded sample from every provider needed by the daily loop."""
    live = queries or default_queries()
    membership = _retry(live.membership)
    members = _membership(membership)
    symbol = sorted(members)[0]
    today = datetime.now(SHANGHAI).date()
    history = _retry(lambda: live.history(symbol, today, today))
    actions = _retry(lambda: live.actions(symbol))
    spot = _retry(live.spot)
    benchmark = _retry(live.benchmark)
    return {
        "membership_count": len(members),
        "sample_symbol": symbol,
        "sample_history_columns": sorted(map(str, history.columns)),
        "sample_action_columns": sorted(map(str, actions.columns)),
        "spot_rows": len(spot),
        "benchmark_rows": len(benchmark),
    }


def capture_live_session(
    data_root: Path,
    *,
    session: date,
    previous_session: date,
    allow_network: bool,
    additional_symbols: Iterable[str] = (),
    queries: LiveQueries | None = None,
    captured_at: datetime | None = None,
) -> Path:
    """Capture one current session with membership, raw bars, status, actions and benchmark."""
    if not allow_network:
        raise ProspectiveCaptureError("--allow-network is required for live prospective capture")
    live = queries or default_queries()
    captured = (captured_at or datetime.now(UTC)).astimezone(UTC)
    members = _membership(_retry(live.membership))
    symbols = tuple(sorted(set(members) | set(additional_symbols)))
    histories, history_failures = _histories(live.history, symbols, previous_session, session)
    spot, spot_warning = _optional_frame(live.spot)
    cached = _latest_action_cache(data_root)
    if _cache_covers_current_capture(cached, captured, symbols):
        assert cached is not None
        actions = cast(list[dict[str, object]], cached["actions"])
        action_failures: list[dict[str, str]] = []
        unresolved_actions: set[str] = set()
    else:
        actions, action_failures = _action_records(live.actions, symbols)
        actions, unresolved_actions = _resolve_action_cache(
            data_root, session, captured, symbols, actions, action_failures
        )
    benchmark, benchmark_warning = _benchmark(live.benchmark, session)
    records, unavailable = _records_for_session(
        session, members, symbols, histories, spot, unresolved_actions
    )
    crosscheck_warning = _crosscheck(records, live.crosscheck)
    if len(members) != 300:
        raise ProspectiveCaptureError(f"CSI300 membership count is {len(members)}, expected 300")
    if len(records) < 200:
        raise ProspectiveCaptureError(f"only {len(records)} usable current bars were captured")
    local = captured.astimezone(SHANGHAI)
    mode = (
        "PROSPECTIVE"
        if local.date() == session and local.timetz().replace(tzinfo=None) >= wall_time(16, 0)
        else "WARM_START_NON_FORMAL"
    )
    capture_status = (
        "COMPLETE"
        if not unavailable
        and not unresolved_actions
        and spot_warning is None
        and benchmark_warning is None
        else "DEGRADED_PROVIDER_FAILURES"
    )
    payload: dict[str, object] = {
        "schema_version": 2,
        "trading_date": session.isoformat(),
        "captured_at": captured.isoformat(),
        "observation_mode": mode,
        "data_capture_status": capture_status,
        "records": records,
        "corporate_actions": actions,
        "benchmark": benchmark,
        "unavailable": unavailable,
        "provider_receipt": {
            "membership": "akshare.index_stock_cons_csindex/000300",
            "bars": "akshare.stock_zh_a_hist_tx/raw",
            "status": "akshare.stock_zh_a_spot_tx",
            "corporate_actions": "akshare.stock_dividend_cninfo",
            "benchmark": "akshare.stock_zh_index_daily_tx/sh000300",
            "history_failures": history_failures,
            "action_failures": action_failures,
            "warnings": [
                item for item in (spot_warning, benchmark_warning, crosscheck_warning) if item
            ],
        },
    }
    return archive_snapshot_payload(payload, data_root, provider="free_public_prospective_v1")


def bootstrap_live_history(
    data_root: Path,
    *,
    sessions: tuple[date, ...],
    allow_network: bool,
    queries: LiveQueries | None = None,
    captured_at: datetime | None = None,
) -> tuple[Path, ...]:
    """Archive retrospective warm-start snapshots without calling them prospective evidence."""
    if not allow_network:
        raise ProspectiveCaptureError("--allow-network is required for warm-start capture")
    if len(sessions) < 60 or tuple(sorted(set(sessions))) != sessions:
        raise ProspectiveCaptureError("warm-start sessions must be sorted, unique and at least 60")
    live = queries or default_queries()
    captured = (captured_at or datetime.now(UTC)).astimezone(UTC)
    members = _membership(_retry(live.membership))
    symbols = tuple(sorted(members))
    histories, failures = _histories(live.history, symbols, sessions[0], sessions[-1])
    actions, action_failures = _action_records(live.actions, symbols)
    actions, unresolved_actions = _resolve_action_cache(
        data_root, sessions[-1], captured, symbols, actions, action_failures
    )
    benchmark_frame, benchmark_warning = _optional_frame(live.benchmark)
    spot, spot_warning = _optional_frame(live.spot)
    receipts: list[Path] = []
    for session in sessions:
        records, unavailable = _records_for_session(
            session, members, symbols, histories, spot, unresolved_actions
        )
        if not records:
            continue
        benchmark = _benchmark_row(benchmark_frame, session)
        payload: dict[str, object] = {
            "schema_version": 2,
            "trading_date": session.isoformat(),
            "captured_at": captured.isoformat(),
            "observation_mode": "WARM_START_NON_FORMAL",
            "data_capture_status": "WARM_START_NON_FORMAL",
            "records": records,
            "corporate_actions": actions,
            "benchmark": benchmark,
            "unavailable": unavailable,
            "provider_receipt": {
                "membership": "current_CSI300_used_for_non_formal_warm_start",
                "bars": "akshare.stock_zh_a_hist_tx/raw",
                "corporate_actions": "retrospective_CNInfo_non_formal",
                "history_failures": failures,
                "action_failures": action_failures,
                "warnings": [item for item in (spot_warning, benchmark_warning) if item],
            },
        }
        receipts.append(
            archive_snapshot_payload(payload, data_root, provider="free_public_warm_start_v1")
        )
    if len(receipts) < 60:
        raise ProspectiveCaptureError(f"warm start archived only {len(receipts)} sessions")
    return tuple(receipts)


def _resolve_action_cache(
    data_root: Path,
    session: date,
    captured: datetime,
    symbols: tuple[str, ...],
    actions: list[dict[str, object]],
    failures: list[dict[str, str]],
) -> tuple[list[dict[str, object]], set[str]]:
    failed = {item["symbol"] for item in failures}
    if failed:
        cached = _latest_action_cache(data_root)
        if cached is None:
            _write_action_cache(
                data_root, session, captured, tuple(sorted(set(symbols) - failed)), actions
            )
            return actions, failed
        cached_session = date.fromisoformat(str(cached["session"]))
        if _action_cache_age_sessions(data_root, cached_session, session) > 5:
            _write_action_cache(
                data_root, session, captured, tuple(sorted(set(symbols) - failed)), actions
            )
            return actions, failed
        covered = set(cast(list[str], cached["covered_symbols"]))
        resolved = failed & covered
        cached_actions = cast(list[dict[str, object]], cached["actions"])
        actions.extend(item for item in cached_actions if str(item["symbol"]) in resolved)
        return (
            sorted(
                actions,
                key=lambda item: (
                    str(item["symbol"]),
                    str(item["effective_date"]),
                    str(item["kind"]),
                ),
            ),
            failed - resolved,
        )
    _write_action_cache(data_root, session, captured, symbols, actions)
    return actions, set()


def _write_action_cache(
    data_root: Path,
    session: date,
    captured: datetime,
    symbols: tuple[str, ...],
    actions: list[dict[str, object]],
) -> None:
    payload = {
        "schema_version": 1,
        "session": session.isoformat(),
        "captured_at": captured.isoformat(),
        "covered_symbols": list(symbols),
        "actions": actions,
    }
    content = json.dumps(payload, ensure_ascii=False, sort_keys=True).encode() + b"\n"
    write_immutable(data_root / "action_ledgers" / f"{sha256(content).hexdigest()}.json", content)


def _latest_action_cache(data_root: Path) -> dict[str, object] | None:
    latest: tuple[tuple[str, int], dict[str, object]] | None = None
    for path in (data_root / "action_ledgers").glob("*.json"):
        value = json.loads(path.read_bytes())
        if not isinstance(value, dict):
            continue
        captured = str(value.get("captured_at", ""))
        coverage = len(cast(list[object], value.get("covered_symbols", [])))
        key = (captured, coverage)
        if latest is None or key > latest[0]:
            latest = (key, cast(dict[str, object], value))
    return latest[1] if latest else None


def _cache_covers_current_capture(
    cache: dict[str, object] | None, captured: datetime, symbols: tuple[str, ...]
) -> bool:
    if cache is None:
        return False
    cached_at = datetime.fromisoformat(str(cache["captured_at"]))
    covered = set(cast(list[str], cache["covered_symbols"]))
    return cached_at.astimezone(UTC).date() == captured.date() and set(symbols) <= covered


def _action_cache_age_sessions(data_root: Path, cached: date, current: date) -> int:
    sessions = set()
    for path in (data_root / "receipts").glob("*.json"):
        value = json.loads(path.read_bytes())
        session = date.fromisoformat(str(value["trading_date"]))
        if cached < session < current:
            sessions.add(session)
    return len(sessions) + int(current > cached)


def _crosscheck(records: list[dict[str, object]], query: SpotQuery | None) -> str | None:
    if query is None:
        return "independent_crosscheck_not_configured"
    try:
        frame = _retry(query)
    except (OSError, ValueError, RuntimeError) as error:
        return f"independent_crosscheck_unavailable: {error}"
    required = {"代码", "今开", "最高", "最低", "最新价"}
    if frame.empty or not required <= set(frame.columns):
        return "independent_crosscheck_schema_mismatch"
    sample = {str(item["symbol"])[-6:]: item for item in records[:30]}
    mismatches = 0
    for _, row in frame.iterrows():
        code = str(row["代码"]).zfill(6)
        if code not in sample:
            continue
        expected = sample[code]
        pairs = (
            (expected["open"], row["今开"]),
            (expected["high"], row["最高"]),
            (expected["low"], row["最低"]),
            (expected["close"], row["最新价"]),
        )
        if any(abs(float(str(left)) - float(str(right))) > 0.011 for left, right in pairs):
            mismatches += 1
    return f"independent_price_mismatches={mismatches}" if mismatches else None


def _membership(frame: pd.DataFrame) -> dict[str, dict[str, str]]:
    required = {"日期", "成分券代码", "成分券名称", "交易所"}
    if frame.empty or not required <= set(frame.columns):
        raise ProspectiveCaptureError("CSI membership response lacks required columns")
    result: dict[str, dict[str, str]] = {}
    for _, values in frame.iterrows():
        code = str(values["成分券代码"]).zfill(6)
        exchange = "SSE" if "上海" in str(values["交易所"]) else "SZSE"
        symbol = ("sh" if exchange == "SSE" else "sz") + code
        if symbol in result:
            raise ProspectiveCaptureError(f"duplicate CSI member: {symbol}")
        result[symbol] = {
            "name": str(values["成分券名称"]),
            "exchange": exchange,
            "source_date": str(values["日期"]),
        }
    return result


def _histories(
    query: HistoryQuery, symbols: tuple[str, ...], start: date, end: date
) -> tuple[dict[str, pd.DataFrame], list[dict[str, str]]]:
    def one(symbol: str) -> tuple[str, pd.DataFrame | None, str | None]:
        try:
            frame = _retry(lambda: query(symbol, start, end))
            _validate_history(frame)
            return symbol, frame, None
        except (KeyError, OSError, ValueError, RuntimeError) as error:
            return symbol, None, str(error)

    with ThreadPoolExecutor(max_workers=2) as executor:
        outcomes = tuple(executor.map(one, symbols))
    histories = {symbol: frame for symbol, frame, _ in outcomes if frame is not None}
    failures = [
        {"symbol": symbol, "error": error or "unknown"}
        for symbol, frame, error in outcomes
        if frame is None
    ]
    return histories, failures


def _action_records(
    query: ActionQuery, symbols: tuple[str, ...]
) -> tuple[list[dict[str, object]], list[dict[str, str]]]:
    def one(symbol: str) -> tuple[list[dict[str, object]], dict[str, str] | None]:
        try:
            frame = _retry(lambda: query(symbol))
            return _normalize_actions(symbol, frame), None
        except (KeyError, OSError, ValueError, RuntimeError) as error:
            return [], {"symbol": symbol, "error": str(error)}

    with ThreadPoolExecutor(max_workers=2) as executor:
        outcomes = tuple(executor.map(one, symbols))
    actions = [action for records, _ in outcomes for action in records]
    failures = [failure for _, failure in outcomes if failure is not None]
    return sorted(
        actions,
        key=lambda item: (str(item["symbol"]), str(item["effective_date"]), str(item["kind"])),
    ), failures


def _normalize_actions(symbol: str, frame: pd.DataFrame) -> list[dict[str, object]]:
    if frame.empty:
        return []
    required = {
        "实施方案公告日期",
        "送股比例",
        "转增比例",
        "派息比例",
        "股权登记日",
        "除权日",
        "派息日",
    }
    if not required <= set(frame.columns):
        raise ProspectiveCaptureError("CNInfo dividend response lacks required columns")
    canonical = frame.fillna("").astype(str).to_csv(index=False, lineterminator="\n").encode()
    digest = sha256(canonical).hexdigest()
    url = f"https://webapi.cninfo.com.cn/api/sysapi/p_sysapi1139?scode={symbol[-6:]}"
    records: list[dict[str, object]] = []
    for _, row in frame.iterrows():
        announcement = _date_text(row["实施方案公告日期"])
        effective = _date_text(row["除权日"])
        if not announcement or not effective:
            continue
        common = {
            "symbol": symbol,
            "announcement_date": announcement,
            "effective_date": effective,
            "record_date": _date_text(row["股权登记日"]),
            "payment_date": _date_text(row["派息日"]),
            "source_url": url,
            "source_sha256": digest,
        }
        cash = _number(row["派息比例"])
        if cash > 0:
            records.append({**common, "kind": "cash_distribution", "cash_per_unit": cash / 10})
        split = (_number(row["送股比例"]) + _number(row["转增比例"])) / 10
        if split > 0:
            records.append({**common, "kind": "share_split", "split_ratio": 1 + split})
    return records


def _records_for_session(
    session: date,
    members: dict[str, dict[str, str]],
    symbols: tuple[str, ...],
    histories: dict[str, pd.DataFrame],
    spot: pd.DataFrame,
    unresolved_actions: set[str],
) -> tuple[list[dict[str, object]], list[dict[str, str]]]:
    spot_map = _spot_map(spot)
    records: list[dict[str, object]] = []
    unavailable: list[dict[str, str]] = []
    for symbol in symbols:
        frame = histories.get(symbol)
        if frame is None or frame.empty:
            unavailable.append({"symbol": symbol, "reason": "provider_failure"})
            continue
        normalized = frame.copy()
        normalized["date"] = pd.to_datetime(normalized["date"]).dt.date
        today = normalized.loc[normalized["date"] == session]
        if today.empty:
            unavailable.append({"symbol": symbol, "reason": "no_daily_bar"})
            continue
        row = today.iloc[-1]
        prior = normalized.loc[normalized["date"] < session]
        previous = float(prior.iloc[-1]["close"]) if len(prior) else float(row["open"])
        info = members.get(symbol, {})
        quote = spot_map.get(symbol, {})
        name = quote.get("name", info.get("name", ""))
        state = quote.get("state", "")
        records.append(
            {
                "symbol": symbol,
                "name": name,
                "open": float(row["open"]),
                "high": float(row["high"]),
                "low": float(row["low"]),
                "close": float(row["close"]),
                "previous_close": previous,
                "volume": float(row["volume"]),
                "amount": float(row["amount"]),
                "member": symbol in members,
                "st": "ST" in name.upper(),
                "suspended": state.lower() in {"suspended", "停牌"} or float(row["volume"]) == 0,
                "exchange": info.get("exchange", _exchange(symbol)),
                "board": _board(symbol),
                "status_source": "tencent_spot_and_daily_bar",
                "action_status": "unknown"
                if symbol in unresolved_actions
                else "complete_or_no_event",
            }
        )
    return records, unavailable


def _spot_map(frame: pd.DataFrame) -> dict[str, dict[str, str]]:
    if frame.empty or not {"code", "name", "state"} <= set(frame.columns):
        return {}
    return {
        str(row.code): {"name": str(row.name), "state": str(row.state)}
        for row in frame.itertuples()
    }


def _benchmark(query: BenchmarkQuery, session: date) -> tuple[dict[str, object], str | None]:
    frame, warning = _optional_frame(query)
    return _benchmark_row(frame, session), warning


def _benchmark_row(frame: pd.DataFrame, session: date) -> dict[str, object]:
    if frame.empty or "date" not in frame:
        return {}
    dates = pd.to_datetime(frame["date"]).dt.date
    rows = frame.loc[dates == session]
    if rows.empty:
        return {}
    row = rows.iloc[-1]
    return {
        key: float(row[key]) for key in ("open", "high", "low", "close", "amount") if key in row
    }


def _optional_frame(query: Callable[[], pd.DataFrame]) -> tuple[pd.DataFrame, str | None]:
    try:
        return _retry(query), None
    except (KeyError, OSError, ValueError, RuntimeError) as error:
        return pd.DataFrame(), str(error)


def _validate_history(frame: pd.DataFrame) -> None:
    required = {"date", "open", "high", "low", "close", "volume", "amount"}
    if not frame.empty and not required <= set(frame.columns):
        raise ProspectiveCaptureError("Tencent history response lacks required columns")


def _retry(call: Callable[[], pd.DataFrame], attempts: int = 3) -> pd.DataFrame:
    last: Exception | None = None
    for attempt in range(attempts):
        try:
            return call()
        except (KeyError, OSError, ValueError, RuntimeError) as error:
            last = error
            if attempt + 1 < attempts:
                time.sleep((1, 5, 20)[attempt])
    raise ProspectiveCaptureError(str(last or "provider request failed"))


def _board(symbol: str) -> str:
    code = symbol[-6:]
    if code.startswith("688"):
        return "star"
    if code.startswith(("300", "301")):
        return "chinext"
    return "main"


def _exchange(symbol: str) -> str:
    return "SSE" if symbol.startswith("sh") else "SZSE"


def _date_text(value: object) -> str | None:
    text = str(value)
    if value is None or text in {"", "NaT", "nan", "None"}:
        return None
    return pd.Timestamp(text).date().isoformat()


def _number(value: object) -> float:
    text = str(value)
    if value is None or text in {"", "nan", "None"}:
        return 0.0
    return float(text)


def write_probe(path: Path, payload: dict[str, object]) -> Path:
    """Persist a content-addressed source-probe result for later diagnosis."""
    content = json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2).encode() + b"\n"
    target = path / f"{sha256(content).hexdigest()}.json"
    write_immutable(target, content)
    return target
