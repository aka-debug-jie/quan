"""Offline-first daily orchestration for the local paper accounts."""

from __future__ import annotations

import fcntl
import json
import subprocess
from dataclasses import asdict
from datetime import UTC, date, datetime
from decimal import Decimal
from hashlib import sha256
from pathlib import Path
from uuid import NAMESPACE_URL, uuid5

import pandas as pd
import yaml

from quant_stack.benchmarks import same_universe_equal_weight_targets
from quant_stack.costs import CostModel
from quant_stack.d0_inventory import load_d0_source_registry
from quant_stack.data.calendar import ExchangeCalendarStore
from quant_stack.data.corporate_actions import load_corporate_action_ledger
from quant_stack.data.evidence import require_corporate_action_evidence
from quant_stack.data.models import (
    CorporateActionLedger,
    D0SourceRegistry,
    ETFHistoryRequest,
    ETFUniverseInstrument,
    ProviderSeriesManifest,
)
from quant_stack.data.provider_series import load_provider_series
from quant_stack.data.sina_etf import fetch_sina_etf_history, persist_sina_etf_history
from quant_stack.data.sse_official import fetch_sse_daily_history, persist_sse_daily_history
from quant_stack.features import calculate_features
from quant_stack.models import DailyBar, PriceBasis, Side
from quant_stack.paper_broker import PaperBroker
from quant_stack.paper_models import PaperBrokerConfig, PaperOrder, PaperSnapshot
from quant_stack.paper_report import write_paper_report
from quant_stack.snapshot import write_immutable
from quant_stack.strategy import monthly_etf_momentum_targets


class PaperDailyError(ValueError):
    """Raised when a daily paper run cannot safely reach a complete snapshot."""


def load_paper_environment(path: Path) -> dict[str, object]:
    """Load the fixed local paper environment and reject live-order capability."""
    payload = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict) or payload.get("mode") != "paper":
        raise PaperDailyError("paper environment must declare mode: paper")
    if payload.get("allow_live_orders") is not False:
        raise PaperDailyError("paper environment must forbid live orders")
    return payload


def initialize_paper_account(environment_path: Path, artifact_root: Path) -> PaperBroker:
    """Create the strategy account and shadow benchmark account idempotently."""
    environment = load_paper_environment(environment_path)
    costs = _costs(Path(str(environment["cost_config"])))
    account = str(environment["account_id"])
    capital = Decimal(str(environment["initial_cash"]))
    for suffix in ("strategy", "benchmark"):
        PaperBroker(
            artifact_root / account / f"{suffix}.sqlite3",
            PaperBrokerConfig(f"{account}:{suffix}", costs, capital),
        ).initialize()
    return PaperBroker(
        artifact_root / account / "strategy.sqlite3",
        PaperBrokerConfig(f"{account}:strategy", costs, capital),
    )


def run_paper_daily(
    environment_path: Path,
    data_root: Path,
    artifact_root: Path,
    trading_date: date,
    *,
    allow_network: bool,
    generated_at: datetime | None = None,
    is_backfill: bool = False,
) -> Path:
    """Refresh approved raw sources, process one paper date, and write an offline report."""
    lock_path = artifact_root / "paper-daily.lock"
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    with lock_path.open("a+", encoding="utf-8") as lock:
        try:
            fcntl.flock(lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as error:
            raise PaperDailyError("another paper daily run is active") from error
        try:
            return _run_paper_daily_locked(
                environment_path,
                data_root,
                artifact_root,
                trading_date,
                allow_network=allow_network,
                generated_at=generated_at or datetime.now(UTC),
                is_backfill=is_backfill,
            )
        except Exception as error:
            content = (
                json.dumps(
                    {
                        "trading_date": trading_date.isoformat(),
                        "exception_type": type(error).__name__,
                        "message": str(error),
                    },
                    sort_keys=True,
                ).encode()
                + b"\n"
            )
            digest = sha256(content).hexdigest()
            write_immutable(artifact_root / "failures" / f"{digest}.json", content)
            raise


def run_paper_catchup(
    environment_path: Path,
    data_root: Path,
    artifact_root: Path,
    as_of: date,
    *,
    allow_network: bool,
) -> tuple[Path, ...]:
    """Process every common confirmed session after the last completed paper snapshot."""
    environment = load_paper_environment(environment_path)
    initialize_paper_account(environment_path, artifact_root)
    universe = _universe(Path(str(environment["universe"])))
    calendar = ExchangeCalendarStore(Path(str(environment["calendar_root"])))
    completed = _completed_dates(artifact_root, str(environment["account_id"]))
    pending = _pending_dates(artifact_root, str(environment["account_id"])) - completed
    start = max(completed) if completed else as_of
    dates = {
        session
        for session in calendar.sessions_between(universe[0].exchange, start, as_of)
        if (not completed or session > start)
        and all(calendar.is_session(item.exchange, session) for item in universe)
    }
    dates.update(session for session in pending if session <= as_of)
    if not completed and calendar.is_session(universe[0].exchange, as_of):
        dates.add(as_of)
    generated_at = datetime.now(UTC)
    return tuple(
        run_paper_daily(
            environment_path,
            data_root,
            artifact_root,
            session,
            allow_network=allow_network,
            generated_at=generated_at,
            is_backfill=session < as_of,
        )
        for session in sorted(dates)
    )


def _run_paper_daily_locked(
    environment_path: Path,
    data_root: Path,
    artifact_root: Path,
    trading_date: date,
    *,
    allow_network: bool,
    generated_at: datetime,
    is_backfill: bool,
) -> Path:
    """Execute the locked daily workflow after the process-level exclusion gate."""
    environment = load_paper_environment(environment_path)
    if not allow_network or environment.get("allow_network_data_download") is not True:
        raise PaperDailyError("paper refresh requires explicit network authorization")
    universe_path = Path(str(environment["universe"]))
    registry_path = Path(str(environment["source_registry"]))
    calendar = ExchangeCalendarStore(Path(str(environment["calendar_root"])))
    universe = _universe(universe_path)
    sessions = {calendar.is_session(item.exchange, trading_date) for item in universe}
    if sessions == {False}:
        noop = artifact_root / str(environment["account_id"]) / "runs" / f"{trading_date}.noop.json"
        write_immutable(
            noop,
            json.dumps(
                {"status": "NON_SESSION", "trading_date": trading_date.isoformat()}, sort_keys=True
            ).encode()
            + b"\n",
        )
        return noop
    if sessions != {True}:
        raise PaperDailyError("paper universe exchanges disagree on session status")
    account = str(environment["account_id"])
    pending_path = artifact_root / account / "pending" / f"{trading_date.isoformat()}.json"
    if pending_path.is_file():
        pending = json.loads(pending_path.read_bytes())
        generated_at = datetime.fromisoformat(str(pending["generated_at"]))
        is_backfill = bool(pending["is_backfill"])
    else:
        write_immutable(
            pending_path,
            json.dumps(
                {
                    "schema_version": "1.0.0",
                    "account_id": account,
                    "trading_date": trading_date.isoformat(),
                    "generated_at": generated_at.isoformat(),
                    "is_backfill": is_backfill,
                    "status": "PENDING",
                },
                sort_keys=True,
                separators=(",", ":"),
            ).encode()
            + b"\n",
        )
    registry = load_d0_source_registry(registry_path, universe_path)
    prepared_path = artifact_root / account / "prepared" / f"{trading_date.isoformat()}.json"
    prepared_is_new = not prepared_path.is_file()
    if prepared_path.is_file():
        prepared = json.loads(prepared_path.read_bytes())
        manifests, raw = _load_prepared_raw(prepared, data_root)
        source_id = _manifest_identity(manifests)
        if prepared.get("source_manifest_id") != source_id:
            raise PaperDailyError("prepared paper input identity mismatch")
    else:
        manifests, raw = _refresh_primary_raw(universe, registry, trading_date, data_root)
        source_id = _manifest_identity(manifests)
    for item in universe:
        dates = {bar.trading_date for bar in raw[item.symbol]}
        coverage = calendar.coverage_report(
            item,
            PriceBasis.RAW,
            dates,
            item.effective_from,
            trading_date,
            documented_non_trading_events=item.documented_non_trading_events,
        )
        if not coverage.is_complete:
            raise PaperDailyError("primary raw coverage has unresolved expected sessions")
    ledgers = {
        item.symbol: load_corporate_action_ledger(
            Path(str(environment["ledger_root"])) / f"{item.symbol}_v1.yaml"
        )
        for item in universe
    }
    for ledger in ledgers.values():
        require_corporate_action_evidence(ledger.events, data_root)
    causal = {symbol: _causal_for_paper(bars, ledgers[symbol]) for symbol, bars in raw.items()}
    opens = {symbol: _bar_on(bars, trading_date).open for symbol, bars in raw.items()}
    closes = {symbol: _bar_on(bars, trading_date).close for symbol, bars in raw.items()}
    if prepared_is_new:
        write_immutable(
            prepared_path,
            json.dumps(
                {
                    "schema_version": "1.0.0",
                    "account_id": account,
                    "trading_date": trading_date.isoformat(),
                    "source_manifest_id": source_id,
                    "manifests": {
                        symbol: manifest.manifest_id
                        for symbol, manifest in sorted(manifests.items())
                    },
                },
                sort_keys=True,
                separators=(",", ":"),
            ).encode()
            + b"\n",
        )
    costs = _costs(Path(str(environment["cost_config"])))
    strategy = PaperBroker(
        artifact_root / account / "strategy.sqlite3",
        PaperBrokerConfig(f"{account}:strategy", costs),
    )
    benchmark = PaperBroker(
        artifact_root / account / "benchmark.sqlite3",
        PaperBrokerConfig(f"{account}:benchmark", costs),
    )
    strategy.initialize()
    benchmark.initialize()
    actions = {symbol: ledger.events for symbol, ledger in ledgers.items()}
    strategy_snapshot = strategy.run_daily(
        _run_id(account, "strategy", trading_date, source_id),
        trading_date,
        opens,
        closes,
        source_id,
        actions,
        generated_at=generated_at,
        is_backfill=is_backfill,
    )
    benchmark_snapshot = benchmark.run_daily(
        _run_id(account, "benchmark", trading_date, source_id),
        trading_date,
        opens,
        closes,
        source_id,
        actions,
        generated_at=generated_at,
        is_backfill=is_backfill,
    )
    next_session = _next_session(calendar, universe, trading_date)
    if next_session.month != trading_date.month:
        _place_strategy_orders(
            strategy, causal, closes, strategy_snapshot, trading_date, next_session
        )
        _place_benchmark_orders(benchmark, closes, benchmark_snapshot, trading_date, next_session)
    report = _report_payload(
        account,
        trading_date,
        strategy,
        benchmark,
        strategy_snapshot,
        benchmark_snapshot,
        source_id,
        manifests,
        ledgers,
        environment_path,
    )
    report_path = (
        artifact_root
        / account
        / "reports"
        / f"{_run_id(account, 'report', trading_date, source_id)}.html"
    )
    written = write_paper_report(report, report_path)
    receipt = {
        "schema_version": "1.0.0",
        "account_id": account,
        "trading_date": trading_date.isoformat(),
        "generated_at": strategy_snapshot.generated_at.isoformat()
        if strategy_snapshot.generated_at
        else None,
        "is_backfill": strategy_snapshot.is_backfill,
        "strategy_run_id": strategy_snapshot.run_id,
        "benchmark_run_id": benchmark_snapshot.run_id,
        "strategy_ledger_head": strategy.reconcile().head_hash,
        "benchmark_ledger_head": benchmark.reconcile().head_hash,
        "report_sha256": sha256(written.read_bytes()).hexdigest(),
        "source_manifest_id": source_id,
    }
    write_immutable(
        artifact_root / account / "completed" / f"{trading_date.isoformat()}.json",
        json.dumps(receipt, sort_keys=True, separators=(",", ":")).encode() + b"\n",
    )
    return written


def _refresh_primary_raw(
    universe: tuple[ETFUniverseInstrument, ...],
    registry: D0SourceRegistry,
    as_of: date,
    data_root: Path,
) -> tuple[dict[str, ProviderSeriesManifest], dict[str, list[DailyBar]]]:
    """Fetch complete independent provider histories without provider blending."""
    manifests: dict[str, ProviderSeriesManifest] = {}
    bars: dict[str, list[DailyBar]] = {}
    if {item.symbol for item in registry.assets} != {item.symbol for item in universe}:
        raise PaperDailyError("paper source registry does not match the frozen universe")
    for item in universe:
        request = ETFHistoryRequest(
            instrument=item,
            universe_id="cn_etf_smoke_v2",
            universe_version=2,
            start_date=item.effective_from,
            as_of_date=as_of,
            price_basis=PriceBasis.RAW,
        )
        if item.exchange.value == "SSE":
            manifest = persist_sse_daily_history(
                request, fetch_sse_daily_history(item.symbol), data_root
            )
        else:
            manifest = persist_sina_etf_history(
                request, fetch_sina_etf_history(item.symbol, item.exchange), data_root
            )
        manifests[item.symbol] = manifest
        _, bars[item.symbol] = load_provider_series(manifest.manifest_id, data_root)
    return manifests, bars


def _load_prepared_raw(
    prepared: object, data_root: Path
) -> tuple[dict[str, ProviderSeriesManifest], dict[str, list[DailyBar]]]:
    """Reload only the provider manifests frozen before the first ledger write."""
    if not isinstance(prepared, dict) or not isinstance(prepared.get("manifests"), dict):
        raise PaperDailyError("prepared paper input receipt is invalid")
    manifests: dict[str, ProviderSeriesManifest] = {}
    bars: dict[str, list[DailyBar]] = {}
    for symbol, manifest_id in prepared["manifests"].items():
        if not isinstance(symbol, str) or not isinstance(manifest_id, str):
            raise PaperDailyError("prepared paper manifest identity is invalid")
        manifest, series = load_provider_series(manifest_id, data_root)
        if manifest.instrument.symbol != symbol:
            raise PaperDailyError("prepared paper manifest symbol mismatch")
        manifests[symbol] = manifest
        bars[symbol] = series
    return manifests, bars


def _causal_for_paper(bars: list[DailyBar], ledger: CorporateActionLedger) -> list[DailyBar]:
    """Build the existing PIT causal view locally after complete-ledger validation."""
    from quant_stack.data.canonical import derive_causal_adjusted_bars

    return derive_causal_adjusted_bars(bars, ledger)


def _place_strategy_orders(
    broker: PaperBroker,
    causal: dict[str, list[DailyBar]],
    closes: dict[str, Decimal],
    snapshot: PaperSnapshot,
    trading_date: date,
    next_session: date,
) -> None:
    features = {symbol: calculate_features(bars) for symbol, bars in causal.items()}
    rows = [
        next(row for row in values if row.bar.trading_date == trading_date)
        for values in features.values()
    ]
    targets = monthly_etf_momentum_targets(
        pd.DatetimeIndex([pd.Timestamp(trading_date)]), {trading_date: rows}, 12, 2
    )
    target = targets.get(pd.Timestamp(trading_date))
    if target is not None:
        _place_target_orders(broker, target, closes, snapshot, trading_date, next_session)


def _place_benchmark_orders(
    broker: PaperBroker,
    closes: dict[str, Decimal],
    snapshot: PaperSnapshot,
    trading_date: date,
    next_session: date,
) -> None:
    target = same_universe_equal_weight_targets(
        (pd.Timestamp(trading_date),), tuple(sorted(closes))
    ).get(pd.Timestamp(trading_date))
    if target is not None:
        _place_target_orders(broker, target, closes, snapshot, trading_date, next_session)


def _place_target_orders(
    broker: PaperBroker,
    target: dict[str, Decimal],
    closes: dict[str, Decimal],
    snapshot: PaperSnapshot,
    signal_date: date,
    execution_date: date,
) -> None:
    nav = snapshot.net_asset_value
    for symbol in sorted(closes):
        desired = nav * Decimal(str(target.get(symbol, Decimal("0")))) / closes[symbol]
        current = snapshot.positions.get(symbol, Decimal("0"))
        difference = desired - current
        if difference == 0:
            continue
        side = Side.BUY if difference > 0 else Side.SELL
        quantity = abs(difference)
        identity = (
            f"{signal_date.isoformat()}:{execution_date.isoformat()}:"
            f"{symbol}:{side.value}:{quantity.normalize()}"
        )
        broker.place_order(
            PaperOrder(
                str(uuid5(NAMESPACE_URL, identity)),
                symbol,
                side,
                quantity,
                signal_date,
                execution_date,
            )
        )


def _report_payload(
    account: str,
    trading_date: date,
    strategy: PaperBroker,
    benchmark: PaperBroker,
    strategy_snapshot: PaperSnapshot,
    benchmark_snapshot: PaperSnapshot,
    manifest_id: str,
    manifests: dict[str, ProviderSeriesManifest],
    ledgers: dict[str, CorporateActionLedger],
    environment_path: Path,
) -> dict[str, object]:
    reconciliation = strategy.reconcile()
    strategy_history = strategy.snapshots()
    benchmark_history = benchmark.snapshots()
    benchmark_by_date = {item.as_of_date: item for item in benchmark_history}
    return {
        "run_id": strategy_snapshot.run_id,
        "account_id": account,
        "trading_date": trading_date.isoformat(),
        "generated_at": strategy_snapshot.generated_at.isoformat()
        if strategy_snapshot.generated_at
        else None,
        "is_backfill": strategy_snapshot.is_backfill,
        "cash": str(strategy_snapshot.cash),
        "receivable_dividends": str(strategy_snapshot.receivable_dividends),
        "cumulative_fees": str(strategy_snapshot.cumulative_fees),
        "strategy": {"nav": str(strategy_snapshot.net_asset_value)},
        "benchmark": {"nav": str(benchmark_snapshot.net_asset_value)},
        "positions": [
            {"symbol": symbol, "quantity": str(quantity)}
            for symbol, quantity in strategy_snapshot.positions.items()
        ],
        "fills": [asdict(fill) for fill in strategy.fills()],
        "orders": [asdict(order) for order in strategy.orders()],
        "rejected_orders": [asdict(item) for item in strategy.rejections()],
        "corporate_actions": [],
        "data_anomalies": [],
        "nav_history": [
            {
                "date": item.as_of_date.isoformat(),
                "strategy_nav": str(item.net_asset_value),
                "benchmark_nav": str(benchmark_by_date[item.as_of_date].net_asset_value)
                if item.as_of_date in benchmark_by_date
                else None,
            }
            for item in strategy_history
        ],
        "evidence": {
            "input_manifest": manifest_id,
            "raw_data_sha256": _manifest_identity(manifests),
            "corporate_action_evidence_sha256": _ledger_evidence_hash(ledgers),
            "ledger_head_sha256": reconciliation.head_hash,
            "code_version": _git_commit(),
            "config_sha256": sha256(environment_path.read_bytes()).hexdigest(),
        },
    }


def _manifest_identity(manifests: dict[str, ProviderSeriesManifest]) -> str:
    return sha256(
        "|".join(sorted(item.manifest_id for item in manifests.values())).encode()
    ).hexdigest()


def _ledger_evidence_hash(ledgers: dict[str, CorporateActionLedger]) -> str:
    """Bind the report to the official corporate-action evidence hashes in use."""
    values = [event.evidence.sha256 for ledger in ledgers.values() for event in ledger.events]
    return sha256("|".join(sorted(values)).encode()).hexdigest()


def _git_commit() -> str:
    """Read the local revision identity without network access."""
    try:
        return subprocess.check_output(("git", "rev-parse", "HEAD"), text=True).strip()
    except OSError:
        return "unavailable"


def _bar_on(bars: list[DailyBar], trading_date: date) -> DailyBar:
    return next(bar for bar in bars if bar.trading_date == trading_date)


def _run_id(account: str, kind: str, trading_date: date, manifest_id: str) -> str:
    return str(
        uuid5(NAMESPACE_URL, f"quant-stack/paper/{account}/{kind}/{trading_date}/{manifest_id}")
    )


def _costs(path: Path) -> CostModel:
    payload = yaml.safe_load(path.read_text(encoding="utf-8"))
    return CostModel(
        Decimal(str(payload["commission_rate"])),
        Decimal(str(payload["minimum_commission"])),
        Decimal(str(payload["half_spread_bps"])) / Decimal("10000"),
        Decimal(str(payload["slippage_bps"])) / Decimal("10000"),
    )


def _universe(path: Path) -> tuple[ETFUniverseInstrument, ...]:
    from quant_stack.data.ingest import load_etf_universe

    return load_etf_universe(path).instruments


def _next_session(
    calendar: ExchangeCalendarStore,
    universe: tuple[ETFUniverseInstrument, ...],
    trading_date: date,
) -> date:
    sessions = [calendar.next_session(item.exchange, trading_date) for item in universe]
    if len(set(sessions)) != 1:
        raise PaperDailyError("paper universe does not share one next session")
    return sessions[0]


def _completed_dates(artifact_root: Path, account_id: str) -> set[date]:
    """Return only dates with a complete account-level strategy/benchmark/report receipt."""
    completed = artifact_root / account_id / "completed"
    return {date.fromisoformat(path.stem) for path in completed.glob("*.json") if path.is_file()}


def _pending_dates(artifact_root: Path, account_id: str) -> set[date]:
    """Return attempted dates that may require idempotent account-level recovery."""
    pending = artifact_root / account_id / "pending"
    return {date.fromisoformat(path.stem) for path in pending.glob("*.json") if path.is_file()}
