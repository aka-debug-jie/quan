"""Research-only V2-A dual-momentum signals from Yahoo adjusted closes."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from datetime import date
from decimal import Decimal
from hashlib import sha256
from pathlib import Path

from quant_stack.snapshot import write_immutable
from quant_stack_v2.yahoo_etf import RESEARCH_ADJUSTED_ONLY, YahooSnapshotReport

RISK_SYMBOLS = ("MCHI", "SPY", "EFA", "IEF", "GLD", "DBC")
DEFENSIVE_SYMBOL = "BIL"
LOOKBACK_SESSIONS = 252
SKIP_RECENT_SESSIONS = 21
SELECTION_COUNT = 3


class DualMomentumError(ValueError):
    """Raised when a research-only dual-momentum input is incomplete or misused."""


@dataclass(frozen=True)
class DualMomentumSignal:
    """One immutable month-end target derived only from adjusted research prices."""

    signal_date: date
    input_start_date: date
    input_end_date: date
    selected_symbols: tuple[str, ...]
    target_weights: dict[str, Decimal]
    relative_returns: dict[str, Decimal]


@dataclass(frozen=True)
class DualMomentumReport:
    """Content-addressed V2-A signal evidence; it intentionally has no return metrics."""

    schema_version: int
    dataset_report_sha256: str
    input_manifest_ids: tuple[str, ...]
    config_sha256: str
    usage_level: str
    signals: tuple[DualMomentumSignal, ...]
    anomalies: tuple[str, ...]
    status: str

    @property
    def identity_sha256(self) -> str:
        """Return a stable identity excluding filesystem location and runtime clock."""
        return sha256(_canonical_json(asdict(self))).hexdigest()


def build_dual_momentum_report(
    snapshot: YahooSnapshotReport,
    *,
    dataset_report_sha256: str,
    config_sha256: str,
) -> DualMomentumReport:
    """Build month-end 12-1 dual-momentum targets without any execution simulation."""
    if len(dataset_report_sha256) != 64 or len(config_sha256) != 64:
        raise DualMomentumError("dual-momentum report requires immutable input and config hashes")
    symbols = {item.manifest.symbol for item in snapshot.symbol_snapshots}
    expected = set(RISK_SYMBOLS) | {DEFENSIVE_SYMBOL}
    if symbols != expected:
        raise DualMomentumError("dual-momentum requires exactly the frozen seven-ETF universe")
    if snapshot.anomalies:
        raise DualMomentumError("dual-momentum refuses Yahoo snapshots with data anomalies")
    closes = {
        item.manifest.symbol: {bar.trading_date: bar.adjusted_close for bar in item.adjusted_bars}
        for item in snapshot.symbol_snapshots
    }
    sessions = snapshot.common_trading_dates
    if len(sessions) <= LOOKBACK_SESSIONS:
        raise DualMomentumError("dual-momentum needs more than 252 common sessions")
    if tuple(sorted(set(sessions))) != sessions:
        raise DualMomentumError("dual-momentum requires unique ascending common sessions")
    signals: list[DualMomentumSignal] = []
    for index, session in enumerate(sessions):
        if index < LOOKBACK_SESSIONS:
            continue
        if index + 1 == len(sessions) or sessions[index + 1].month != session.month:
            signals.append(_signal_for_session(session, index, sessions, closes))
    return DualMomentumReport(
        schema_version=1,
        dataset_report_sha256=dataset_report_sha256,
        input_manifest_ids=tuple(
            sorted(item.manifest.manifest_id for item in snapshot.symbol_snapshots)
        ),
        config_sha256=config_sha256,
        usage_level=RESEARCH_ADJUSTED_ONLY,
        signals=tuple(signals),
        anomalies=(),
        status="RESEARCH_SIGNAL_ONLY",
    )


def persist_dual_momentum_report(report: DualMomentumReport, artifact_root: Path) -> Path:
    """Persist research signals immutably below the isolated V2 artifact root."""
    if report.usage_level != RESEARCH_ADJUSTED_ONLY or report.status != "RESEARCH_SIGNAL_ONLY":
        raise DualMomentumError("only research-only dual-momentum reports may be persisted")
    path = artifact_root / "dual_momentum" / report.identity_sha256 / "report.json"
    write_immutable(path, _canonical_json(asdict(report)) + b"\n")
    return path


def reject_execution_use(report: DualMomentumReport, requested_use: str) -> None:
    """Reject every attempt to route adjusted-price V2-A signals to execution or performance use."""
    forbidden = {"execution", "backtest", "paper_broker", "performance", "paper_candidate"}
    if requested_use in forbidden:
        raise DualMomentumError("Yahoo adjusted-price V2-A signals are research-only")


def _signal_for_session(
    session: date,
    index: int,
    sessions: tuple[date, ...],
    closes: dict[str, dict[date, Decimal]],
) -> DualMomentumSignal:
    start = sessions[index - LOOKBACK_SESSIONS]
    end = sessions[index - SKIP_RECENT_SESSIONS]
    returns = {
        symbol: closes[symbol][end] / closes[symbol][start] - Decimal("1") for symbol in closes
    }
    defensive_return = returns[DEFENSIVE_SYMBOL]
    eligible = sorted(
        (symbol for symbol in RISK_SYMBOLS if returns[symbol] > defensive_return),
        key=lambda symbol: (-returns[symbol], symbol),
    )[:SELECTION_COUNT]
    weights: dict[str, Decimal]
    if eligible:
        weight = Decimal("1") / Decimal(len(eligible))
        weights = {symbol: weight for symbol in eligible}
    else:
        weights = {DEFENSIVE_SYMBOL: Decimal("1")}
    return DualMomentumSignal(
        signal_date=session,
        input_start_date=start,
        input_end_date=end,
        selected_symbols=tuple(eligible),
        target_weights=weights,
        relative_returns={symbol: returns[symbol] - defensive_return for symbol in RISK_SYMBOLS},
    )


def _canonical_json(value: object) -> bytes:
    """Serialize Decimal-containing dataclasses deterministically."""
    return json.dumps(value, default=str, sort_keys=True, separators=(",", ":")).encode()
