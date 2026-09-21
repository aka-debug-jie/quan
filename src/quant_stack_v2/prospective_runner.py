"""Idempotent orchestration for the forward-only CSI300 shadow loop."""

from __future__ import annotations

import fcntl
import json
import subprocess
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
    ENGINEERING_ACCOUNT_PHASE,
    ENGINEERING_DATABASE,
    FORMAL_ACCOUNT_PHASE,
    FORMAL_DATABASE,
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
        signal = build_signal(config, receipt, artifact_root, calendar_root=calendar_root)
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
    accounts: dict[str, dict[str, object]] = {}
    for phase, filename, account_id in (
        (ENGINEERING_ACCOUNT_PHASE, ENGINEERING_DATABASE, config.strategy_id),
        (
            FORMAL_ACCOUNT_PHASE,
            FORMAL_DATABASE,
            f"{config.strategy_id}:{FORMAL_ACCOUNT_PHASE}",
        ),
    ):
        path = artifact_root / "paper" / filename
        if not path.exists() and phase == FORMAL_ACCOUNT_PHASE:
            continue
        broker = PaperBroker(
            path,
            PaperBrokerConfig(account_id, config.costs, config.initial_cash),
        )
        snapshot = broker.initialize()
        reconciled = broker.reconcile()
        accounts[phase] = {
            "ledger_head": reconciled.head_hash,
            "nav": str(reconciled.snapshot.net_asset_value),
            "as_of_date": snapshot.as_of_date.isoformat(),
        }
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
        "through": through.isoformat()
        if through
        else max(str(item["as_of_date"]) for item in accounts.values()),
        "artifact_count": len(files),
        "artifact_set_sha256": digest.hexdigest(),
        "accounts": accounts,
    }


def build_acceptance_manifest(
    config_path: Path,
    data_root: Path,
    artifact_root: Path,
    repository_root: Path,
    *,
    validated_commit: str | None = None,
    ci_url: str | None = None,
    ci_head_sha: str | None = None,
    ci_conclusion: str | None = None,
    tests_passed: int | None = None,
    coverage_percent: int | None = None,
) -> dict[str, object]:
    """Build a redacted RC-or-closed operations acceptance record."""
    commit = validated_commit or _git_head(repository_root)
    daily = _daily_reports(artifact_root)
    providers: dict[str, str] = {}
    for path in sorted((data_root / "receipts").glob("*.json")):
        value = _json_object(path)
        providers[path.stem] = str(value.get("provider", ""))
    real = [
        item
        for item in daily
        if providers.get(str(item.get("receipt_sha256", ""))) == "free_public_prospective_v1"
    ]
    first_fill = next(
        (str(item["trading_date"]) for item in real if int(str(item.get("fills_today", 0))) > 0),
        None,
    )
    first_rebalance = next(
        (
            str(item["trading_date"])
            for item in real
            if int(str(item.get("buy_fills_today", 0))) > 0
            and int(str(item.get("sell_fills_today", 0))) > 0
        ),
        None,
    )
    ci_verified = ci_conclusion == "success" and ci_head_sha == commit and bool(ci_url)
    rebuild = rebuild_status(config_path, artifact_root)
    files = (
        config_path,
        repository_root / "configs/v2/prospective/cn_shadow_rules_v1.yaml",
        repository_root / "systemd/user/quant-prospective.service",
        repository_root / "systemd/user/quant-prospective.timer",
    )
    hashes = {
        _relative_name(path, repository_root): sha256(path.read_bytes()).hexdigest()
        for path in files
    }
    missing = [
        label
        for label, ready in (
            ("GREEN_REMOTE_CI", ci_verified),
            ("REAL_T_PLUS_ONE_FILL", first_fill is not None),
            ("REAL_TWO_SIDED_REBALANCE", first_rebalance is not None),
        )
        if not ready
    ]
    latest = daily[-1] if daily else {}
    result: dict[str, object] = {
        "schema_version": 1,
        "acceptance_status": "OPERATIONS_LOOP_CLOSED" if not missing else "OPERATIONS_LOOP_RC",
        "missing_acceptance_evidence": missing,
        "code_commit": commit,
        "ci": {
            "url": ci_url,
            "head_sha": ci_head_sha,
            "conclusion": ci_conclusion,
        },
        "file_sha256": hashes,
        "local_validation": {
            "tests_passed": tests_passed,
            "branch_coverage_percent": coverage_percent,
        },
        "runtime": {
            "first_live_capture_date": str(real[0]["trading_date"]) if real else None,
            "first_live_fill_date": first_fill,
            "first_two_sided_rebalance_date": first_rebalance,
            "receipt_sha256": [str(item["receipt_sha256"]) for item in real],
            "artifact_set_sha256": rebuild["artifact_set_sha256"],
            "accounts": rebuild["accounts"],
        },
        "boundaries": {
            "historical_research": "NO_FORMAL_DATA_QUALIFICATION",
            "profitability": latest.get(
                "PROFITABILITY_STATUS", "INSUFFICIENT_PROSPECTIVE_EVIDENCE"
            ),
            "live_broker": "FORBIDDEN",
            "csi500": "NOT_STARTED",
        },
    }
    result["acceptance_id"] = sha256(
        json.dumps(result, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    return result


def latest_status(artifact_root: Path) -> dict[str, object]:
    """Load the latest consolidated daily JSON without invoking a provider."""
    reports = _daily_reports(artifact_root)
    if not reports:
        raise ProspectiveRunnerError("no prospective daily report exists")
    return reports[-1]


def _held_symbols(config: ShadowConfig, artifact_root: Path) -> tuple[str, ...]:
    formal = artifact_root / "paper" / FORMAL_DATABASE
    path = formal if formal.exists() else artifact_root / "paper" / ENGINEERING_DATABASE
    if not path.exists():
        return ()
    account_id = (
        f"{config.strategy_id}:{FORMAL_ACCOUNT_PHASE}" if path == formal else config.strategy_id
    )
    broker = PaperBroker(path, PaperBrokerConfig(account_id, config.costs, config.initial_cash))
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
        "schema_version": 2,
        "trading_date": session.isoformat(),
        "ENGINEERING_STATUS": "DAILY_RUN_COMPLETE",
        "INPUT_STATUS": signal_payload["INPUT_STATUS"],
        "DATA_CAPTURE_STATUS": signal_payload["DATA_CAPTURE_STATUS"],
        "SHADOW_SIGNAL_STATUS": signal_payload["SHADOW_SIGNAL_STATUS"],
        "PAPER_ACCOUNT_STATUS": paper_payload["PAPER_ACCOUNT_STATUS"],
        "paper_account_phase": paper_payload["paper_account_phase"],
        "PROFITABILITY_STATUS": diagnostic_payload["PROFITABILITY_STATUS"],
        "coverage": signal_payload["coverage"],
        "top": signal_payload["top"],
        "nav": paper_payload["nav"],
        "cash": paper_payload["cash"],
        "positions": paper_payload["positions"],
        "fills_today": paper_payload["fills_today"],
        "buy_fills_today": paper_payload["buy_fills_today"],
        "sell_fills_today": paper_payload["sell_fills_today"],
        "rejections_today": paper_payload["rejections_today"],
        "rules_sha256": paper_payload["rules_sha256"],
        "calendar_sha256": paper_payload["calendar_sha256"],
        "corporate_action_view_sha256": paper_payload["corporate_action_view_sha256"],
        "receipt_sha256": paper_payload["receipt_sha256"],
        "capture_receipt_policy": "FIRST_IMMUTABLE_RECEIPT",
        "OPERATIONS_ACCEPTANCE_STATUS": "OPERATIONS_LOOP_RC",
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
        f"- Capture: `{value['DATA_CAPTURE_STATUS']}`\n"
        f"- Signal: `{value['SHADOW_SIGNAL_STATUS']}`; coverage `{value['coverage']}`\n"
        f"- Paper: `{value['PAPER_ACCOUNT_STATUS']}` / `{value['paper_account_phase']}`; "
        f"NAV `{value['nav']}`\n"
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


def _daily_reports(artifact_root: Path) -> list[dict[str, object]]:
    selected: dict[str, tuple[int, str, dict[str, object]]] = {}
    for path in sorted((artifact_root / "daily").glob("*.json")):
        value = _json_object(path)
        trading_date = str(value.get("trading_date", ""))
        key = (int(str(value.get("schema_version", 0))), path.name, value)
        if trading_date not in selected or key[:2] > selected[trading_date][:2]:
            selected[trading_date] = key
    return [item[2] for _, item in sorted(selected.items())]


def _relative_name(path: Path, repository_root: Path) -> str:
    try:
        return path.resolve().relative_to(repository_root.resolve()).as_posix()
    except ValueError:
        return path.name


def _git_head(repository_root: Path) -> str:
    result = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=repository_root,
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout.strip()


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
