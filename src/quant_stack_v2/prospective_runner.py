"""Idempotent orchestration for the forward-only CSI300 shadow loop."""

from __future__ import annotations

import fcntl
import json
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import date, datetime
from hashlib import sha256
from pathlib import Path
from typing import cast

from quant_stack.data.calendar import ExchangeCalendarStore
from quant_stack.models import Exchange
from quant_stack.paper_broker import PaperBroker
from quant_stack.paper_models import PaperBrokerConfig
from quant_stack.snapshot import write_immutable
from quant_stack_v2.prospective_capture import (
    LiveQueries,
    bootstrap_live_history,
    capture_live_session,
)
from quant_stack_v2.prospective_diagnostics import build_diagnostics
from quant_stack_v2.prospective_shadow import (
    ShadowConfig,
    build_signal,
    load_config,
    run_paper_day,
)


class ProspectiveRunnerError(ValueError):
    """Raised when one prospective daily orchestration cannot finish safely."""


def bootstrap(
    config_path: Path,
    data_root: Path,
    *,
    through: date,
    calendar_root: Path,
    allow_network: bool,
    queries: LiveQueries | None = None,
    captured_at: datetime | None = None,
) -> tuple[Path, ...]:
    """Capture the non-formal feature warm start ending before ``through``."""
    config = load_config(config_path)
    calendar = ExchangeCalendarStore(calendar_root)
    sessions = _previous_sessions(calendar, through, config.maximum_lookback_sessions + 5)
    return bootstrap_live_history(
        data_root,
        sessions=sessions,
        allow_network=allow_network,
        queries=queries,
        captured_at=captured_at,
    )


def run_daily(
    config_path: Path,
    data_root: Path,
    artifact_root: Path,
    *,
    calendar_root: Path,
    rules_path: Path,
    allow_network: bool,
    session: date | None = None,
    queries: LiveQueries | None = None,
    now: datetime | None = None,
) -> Path:
    """Capture, signal, paper-fill, diagnose and report one completed exchange session."""
    config = load_config(config_path)
    calendar = ExchangeCalendarStore(calendar_root)
    target = session or calendar.latest_completed_session(Exchange.SSE, now)
    if target != calendar.latest_completed_session(Exchange.SZSE, now):
        raise ProspectiveRunnerError("latest completed SSE and SZSE sessions differ")
    artifact_root.mkdir(parents=True, exist_ok=True)
    with _run_lock(artifact_root / "state" / "run.lock"):
        if _archived_session_count(data_root, target) < config.maximum_lookback_sessions:
            bootstrap(
                config_path,
                data_root,
                through=target,
                calendar_root=calendar_root,
                allow_network=allow_network,
                queries=queries,
                captured_at=now,
            )
        receipt = _receipt_for_session(data_root, target)
        if receipt is None:
            previous = calendar.previous_session(Exchange.SSE, target)
            additional = _held_symbols(config, artifact_root)
            receipt = capture_live_session(
                data_root,
                session=target,
                previous_session=previous,
                allow_network=allow_network,
                additional_symbols=additional,
                queries=queries,
                captured_at=now,
            )
        signal = build_signal(config, receipt, artifact_root)
        paper = run_paper_day(
            config,
            receipt,
            artifact_root,
            calendar_root=calendar_root,
            rules_path=rules_path,
        )
        diagnostics = build_diagnostics(data_root, artifact_root, target, config=config)
        return _daily_summary(target, receipt, signal, paper, diagnostics, artifact_root)


def rebuild_status(
    config_path: Path, artifact_root: Path, *, through: date | None = None
) -> dict[str, object]:
    """Reconcile the local ledger and hash immutable artifacts through a cutoff."""
    config = load_config(config_path)
    broker = PaperBroker(
        artifact_root / "paper" / "strategy.sqlite3",
        PaperBrokerConfig(config.strategy_id, config.costs, config.initial_cash),
    )
    snapshot = broker.initialize()
    reconciled = broker.reconcile()
    files = [
        path
        for folder in ("signals", "reports", "diagnostics", "daily")
        for path in sorted((artifact_root / folder).glob("*.json"))
        if through is None or _artifact_date(path) <= through
    ]
    digest = sha256()
    for path in files:
        digest.update(path.name.encode())
        digest.update(path.read_bytes())
    return {
        "ENGINEERING_STATUS": "REBUILD_VERIFIED",
        "PAPER_ACCOUNT_STATUS": "RECONCILED_LOCAL_ONLY",
        "through": through.isoformat() if through else snapshot.as_of_date.isoformat(),
        "artifact_count": len(files),
        "artifact_set_sha256": digest.hexdigest(),
        "ledger_head": reconciled.head_hash,
        "nav": str(reconciled.snapshot.net_asset_value),
    }


def latest_status(artifact_root: Path) -> dict[str, object]:
    """Load the latest consolidated daily JSON without invoking a provider."""
    paths = sorted((artifact_root / "daily").glob("*.json"))
    if not paths:
        raise ProspectiveRunnerError("no prospective daily report exists")
    value = json.loads(paths[-1].read_bytes())
    if not isinstance(value, dict):
        raise ProspectiveRunnerError("daily report must be a JSON object")
    return cast(dict[str, object], value)


def _held_symbols(config: ShadowConfig, artifact_root: Path) -> tuple[str, ...]:
    path = artifact_root / "paper" / "strategy.sqlite3"
    if not path.exists():
        return ()
    broker = PaperBroker(
        path, PaperBrokerConfig(config.strategy_id, config.costs, config.initial_cash)
    )
    return tuple(sorted(broker.reconcile().snapshot.positions))


def _previous_sessions(
    calendar: ExchangeCalendarStore, through: date, count: int
) -> tuple[date, ...]:
    values: list[date] = []
    cursor = through
    for _ in range(count):
        cursor = calendar.previous_session(Exchange.SSE, cursor)
        values.append(cursor)
    return tuple(reversed(values))


def _archived_session_count(data_root: Path, through: date) -> int:
    sessions: set[str] = set()
    for path in (data_root / "receipts").glob("*.json"):
        value = json.loads(path.read_bytes())
        session = str(value.get("trading_date", ""))
        if session and date.fromisoformat(session) <= through:
            sessions.add(session)
    return len(sessions)


def _receipt_for_session(data_root: Path, session: date) -> Path | None:
    candidates: list[tuple[str, Path]] = []
    for path in (data_root / "receipts").glob("*.json"):
        value = json.loads(path.read_bytes())
        if value.get("trading_date") == session.isoformat():
            candidates.append((str(value["captured_at"]), path))
    return min(candidates)[1] if candidates else None


def _daily_summary(
    session: date,
    receipt: Path,
    signal: Path,
    paper: Path,
    diagnostics: Path,
    artifact_root: Path,
) -> Path:
    signal_payload = _json_object(signal)
    paper_payload = _json_object(paper)
    diagnostic_payload = _json_object(diagnostics)
    result = {
        "schema_version": 1,
        "trading_date": session.isoformat(),
        "ENGINEERING_STATUS": "DAILY_RUN_COMPLETE",
        "INPUT_STATUS": signal_payload["INPUT_STATUS"],
        "SHADOW_SIGNAL_STATUS": signal_payload["SHADOW_SIGNAL_STATUS"],
        "PAPER_ACCOUNT_STATUS": paper_payload["PAPER_ACCOUNT_STATUS"],
        "PROFITABILITY_STATUS": diagnostic_payload["PROFITABILITY_STATUS"],
        "coverage": signal_payload["coverage"],
        "top": signal_payload["top"],
        "nav": paper_payload["nav"],
        "cash": paper_payload["cash"],
        "positions": paper_payload["positions"],
        "fills_today": paper_payload["fills_today"],
        "rejections_today": paper_payload["rejections_today"],
        "rules_sha256": paper_payload["rules_sha256"],
        "calendar_sha256": paper_payload["calendar_sha256"],
        "mean_ic": diagnostic_payload["mean_ic"],
        "mean_rank_ic": diagnostic_payload["mean_rank_ic"],
        "direction_consistency": diagnostic_payload["direction_consistency"],
        "artifacts": {
            "receipt": str(receipt.resolve()),
            "signal": str(signal.resolve()),
            "paper": str(paper.resolve()),
            "diagnostics": str(diagnostics.resolve()),
        },
    }
    content = json.dumps(result, ensure_ascii=False, sort_keys=True, indent=2).encode() + b"\n"
    path = artifact_root / "daily" / f"{session.isoformat()}-{sha256(content).hexdigest()}.json"
    write_immutable(path, content)
    markdown = _markdown(result)
    write_immutable(path.with_suffix(".md"), markdown.encode("utf-8"))
    return path


def _markdown(value: dict[str, object]) -> str:
    return (
        f"# CN shadow {value['trading_date']}\n\n"
        f"- Engineering: `{value['ENGINEERING_STATUS']}`\n"
        f"- Input: `{value['INPUT_STATUS']}`\n"
        f"- Signal: `{value['SHADOW_SIGNAL_STATUS']}`; coverage `{value['coverage']}`\n"
        f"- Paper: `{value['PAPER_ACCOUNT_STATUS']}`; NAV `{value['nav']}`\n"
        f"- Profitability: `{value['PROFITABILITY_STATUS']}`\n"
        f"- Mean IC / Rank-IC: `{value['mean_ic']}` / `{value['mean_rank_ic']}`\n"
        f"- Fills / rejections: `{value['fills_today']}` / "
        f"`{len(cast(list[object], value['rejections_today']))}`\n"
    )


def _json_object(path: Path) -> dict[str, object]:
    value = json.loads(path.read_bytes())
    if not isinstance(value, dict):
        raise ProspectiveRunnerError(f"artifact must be an object: {path}")
    return cast(dict[str, object], value)


def _artifact_date(path: Path) -> date:
    return date.fromisoformat(path.name[:10]) if path.name[:10].count("-") == 2 else date.min


@contextmanager
def _run_lock(path: Path) -> Iterator[None]:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a+", encoding="utf-8") as handle:
        try:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as error:
            raise ProspectiveRunnerError("another prospective daily run is active") from error
        try:
            yield
        finally:
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
