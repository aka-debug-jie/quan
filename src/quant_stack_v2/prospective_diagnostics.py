"""Delayed, forward-only IC and paper diagnostics for prospective signals."""

from __future__ import annotations

import json
import math
from datetime import date
from hashlib import sha256
from pathlib import Path
from typing import cast

import numpy as np
import pandas as pd

from quant_stack.paper_broker import PaperBroker
from quant_stack.paper_models import PaperBrokerConfig
from quant_stack.snapshot import write_immutable
from quant_stack_v2.prospective_shadow import ShadowConfig, _history


def build_diagnostics(
    data_root: Path,
    artifact_root: Path,
    through: date,
    *,
    config: ShadowConfig | None = None,
) -> Path:
    """Evaluate signals only after both T+1 and T+2 closes are archived."""
    history = _history(data_root, through)
    sessions = sorted(item.date() for item in history.session.unique())
    rows: list[dict[str, object]] = []
    signals = _signals_by_date(artifact_root, through)
    for signal_day, signal in sorted(signals.items()):
        if signal_day not in sessions or sessions.index(signal_day) + 2 >= len(sessions):
            continue
        t1, t2 = sessions[sessions.index(signal_day) + 1 : sessions.index(signal_day) + 3]
        score_rows = signal.get("scores", [])
        if not isinstance(score_rows, list):
            continue
        scores = pd.DataFrame(cast(list[dict[str, object]], score_rows))
        if len(scores) < 2:
            continue
        price = history.loc[
            history.symbol.isin(scores.symbol)
            & history.session.isin([pd.Timestamp(t1), pd.Timestamp(t2)]),
            ["symbol", "session", "calc_close"],
        ]
        pivot = price.pivot(index="symbol", columns="session", values="calc_close")
        if pivot.shape[1] != 2:
            continue
        label = pivot.iloc[:, 1] / pivot.iloc[:, 0] - 1
        joined = scores.set_index("symbol").join(label.rename("label"), how="inner").dropna()
        if len(joined) < 2:
            continue
        rank_ic = float(joined.score.corr(joined.label, method="spearman"))
        rows.append(
            {
                "signal_date": signal_day.isoformat(),
                "label_start": t1.isoformat(),
                "label_end": t2.isoformat(),
                "input_status": signal.get("INPUT_STATUS", "WARM_START_NON_FORMAL"),
                "rows": len(joined),
                "coverage": len(joined) / len(scores),
                "ic": float(joined.score.corr(joined.label, method="pearson")),
                "rank_ic": rank_ic,
                "rank_ic_positive": rank_ic > 0,
                "top_minus_bottom": float(
                    joined.nlargest(max(1, len(joined) // 5), "score").label.mean()
                    - joined.nsmallest(max(1, len(joined) // 5), "score").label.mean()
                ),
            }
        )
    prospective = [row for row in rows if row["input_status"] == "FULLY_PROSPECTIVE_INPUT"]
    mean_ic = _mean(prospective, "ic")
    mean_rank_ic = _mean(prospective, "rank_ic")
    direction = _mean(prospective, "rank_ic_positive")
    coverage = _mean(prospective, "coverage")
    signal_status, profitability = _signal_decision(
        prospective, mean_rank_ic, direction, coverage, config
    )
    paper = _paper_metrics(data_root, artifact_root, config)
    if profitability == "PROSPECTIVE_SIGNAL_SUPPORTED" and int(
        str(paper.get("evaluated_days", 0))
    ) >= (config.minimum_fully_prospective_days if config else 60):
        strategy_return = cast(float | None, paper.get("total_return"))
        benchmark_return = cast(float | None, paper.get("benchmark_return"))
        profitability = (
            "PAPER_RESEARCH_CANDIDATE"
            if strategy_return is not None
            and benchmark_return is not None
            and strategy_return > benchmark_return
            else "NO_COST_ADJUSTED_EDGE"
        )
    result = {
        "schema_version": 2,
        "through": through.isoformat(),
        "ENGINEERING_STATUS": "DIAGNOSTICS_STAGE_COMPLETE",
        "INPUT_STATUS": "FULLY_PROSPECTIVE_INPUT" if prospective else "WARM_START_NON_FORMAL",
        "SHADOW_SIGNAL_STATUS": signal_status,
        "PAPER_ACCOUNT_STATUS": "RECONCILED_LOCAL_ONLY" if paper else "NOT_STARTED",
        "PROFITABILITY_STATUS": profitability,
        "days": rows,
        "fully_prospective_days": len(prospective),
        "mean_ic": mean_ic,
        "mean_rank_ic": mean_rank_ic,
        "direction_consistency": direction,
        "evaluation_coverage": coverage,
        "paper_metrics": paper,
    }
    content = json.dumps(result, sort_keys=True, separators=(",", ":")).encode() + b"\n"
    path = (
        artifact_root / "diagnostics" / f"{through.isoformat()}-{sha256(content).hexdigest()}.json"
    )
    write_immutable(path, content)
    return path


def _signal_decision(
    rows: list[dict[str, object]],
    mean_rank_ic: float | None,
    direction: float | None,
    coverage: float | None,
    config: ShadowConfig | None,
) -> tuple[str, str]:
    minimum_days = config.minimum_fully_prospective_days if config else 60
    minimum_coverage = config.minimum_evaluation_coverage if config else 0.5
    minimum_direction = config.minimum_direction_consistency if config else 0.5
    if len(rows) < minimum_days:
        return "INSUFFICIENT_LABELS", "INSUFFICIENT_PROSPECTIVE_EVIDENCE"
    supported = (
        mean_rank_ic is not None
        and mean_rank_ic > 0
        and direction is not None
        and direction >= minimum_direction
        and coverage is not None
        and coverage >= minimum_coverage
    )
    return (
        ("PROSPECTIVE_SIGNAL_SUPPORTED", "PROSPECTIVE_SIGNAL_SUPPORTED")
        if supported
        else ("NO_PROSPECTIVE_SIGNAL", "NO_PROSPECTIVE_SIGNAL")
    )


def _paper_metrics(
    data_root: Path, artifact_root: Path, config: ShadowConfig | None
) -> dict[str, object]:
    reports = []
    for path in sorted((artifact_root / "reports").glob("*.json")):
        value = json.loads(path.read_bytes())
        if value.get("INPUT_STATUS") == "FULLY_PROSPECTIVE_INPUT":
            reports.append(value)
    if not reports:
        return {}
    frame = (
        pd.DataFrame(
            {
                "date": [date.fromisoformat(str(row["trading_date"])) for row in reports],
                "nav": [float(row["nav"]) for row in reports],
            }
        )
        .drop_duplicates("date", keep="first")
        .sort_values("date")
    )
    returns = frame.nav.pct_change().dropna()
    drawdown = frame.nav / frame.nav.cummax() - 1
    benchmark = _benchmark_closes(data_root)
    benchmark_values = [benchmark.get(item) for item in frame.date]
    valid_benchmark = [item for item in benchmark_values if item is not None]
    benchmark_return = (
        valid_benchmark[-1] / valid_benchmark[0] - 1 if len(valid_benchmark) >= 2 else None
    )
    trades = 0
    turnover_notional = 0.0
    if config is not None and (artifact_root / "paper" / "strategy.sqlite3").exists():
        broker = PaperBroker(
            artifact_root / "paper" / "strategy.sqlite3",
            PaperBrokerConfig(config.strategy_id, config.costs, config.initial_cash),
        )
        fills = broker.fills()
        trades = len(fills)
        turnover_notional = sum(float(fill.notional) for fill in fills)
    years = len(returns) / 252 if len(returns) else 0.0
    total_return = frame.nav.iloc[-1] / frame.nav.iloc[0] - 1 if len(frame) >= 2 else None
    volatility = float(returns.std(ddof=1) * math.sqrt(252)) if len(returns) >= 2 else None
    sharpe = (
        float(returns.mean() / returns.std(ddof=1) * math.sqrt(252))
        if len(returns) >= 2 and returns.std(ddof=1) > 0
        else None
    )
    return {
        "evaluated_days": len(frame),
        "total_return": float(total_return) if total_return is not None else None,
        "cagr": float((1 + total_return) ** (1 / years) - 1)
        if total_return is not None and years > 0 and 1 + total_return > 0
        else None,
        "volatility": volatility,
        "sharpe": sharpe,
        "maximum_drawdown": float(drawdown.min()),
        "turnover": turnover_notional / float(frame.nav.mean()),
        "trade_count": trades,
        "benchmark_return": float(benchmark_return) if benchmark_return is not None else None,
    }


def _benchmark_closes(data_root: Path) -> dict[date, float]:
    selected: dict[date, tuple[str, float]] = {}
    for manifest in sorted((data_root / "raw").glob("*/manifest.json")):
        meta = json.loads(manifest.read_bytes())
        source = manifest.parent / str(meta["files"][0]["relative_path"])
        payload = json.loads(source.read_bytes())
        benchmark = payload.get("benchmark", {})
        if isinstance(benchmark, dict) and benchmark.get("close") is not None:
            session = date.fromisoformat(str(payload["trading_date"]))
            captured = str(payload["captured_at"])
            if session not in selected or captured < selected[session][0]:
                selected[session] = (captured, float(benchmark["close"]))
    return {session: value for session, (_, value) in selected.items()}


def _signals_by_date(artifact_root: Path, through: date) -> dict[date, dict[str, object]]:
    result: dict[date, dict[str, object]] = {}
    for path in sorted((artifact_root / "signals").glob("*.json")):
        value = json.loads(path.read_bytes())
        signal_day = date.fromisoformat(str(value["trading_date"]))
        if signal_day <= through and signal_day not in result:
            result[signal_day] = cast(dict[str, object], value)
    return result


def _mean(rows: list[dict[str, object]], field: str) -> float | None:
    values = [
        (1.0 if row[field] is True else 0.0)
        if isinstance(row[field], bool)
        else float(str(row[field]))
        for row in rows
        if row.get(field) is not None
    ]
    return float(np.mean(values)) if values else None
