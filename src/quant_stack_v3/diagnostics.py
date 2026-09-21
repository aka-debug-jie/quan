"""Signal-only IC, Rank-IC, horizon, and top-minus-bottom diagnostics."""

from __future__ import annotations

import math
from dataclasses import asdict, dataclass
from hashlib import sha256
from pathlib import Path

import numpy as np
import pandas as pd

from quant_stack.research_json import canonical_json
from quant_stack.snapshot import write_immutable


@dataclass(frozen=True)
class HorizonSummary:
    """Aggregate diagnostics for one explicitly defined forward label."""

    label: str
    evaluated_rows: int
    evaluated_days: int
    mean_ic: float
    mean_rank_ic: float
    rank_ic_newey_west_se_lag20: float
    positive_rank_ic_day_fraction: float
    mean_top20_minus_bottom20: float
    yearly_rank_ic: dict[str, float]


def build_signal_diagnostics(
    bars_path: Path,
    scores_path: Path,
    output_root: Path,
) -> tuple[Path, dict[str, object]]:
    """Evaluate the frozen score against old-label and tradable open horizons."""
    scores = pd.read_parquet(scores_path)
    bars = pd.read_parquet(
        bars_path,
        columns=["session", "symbol", "session_ordinal", "calc_close", "calc_open"],
    )
    frame = scores.merge(
        bars.loc[:, ["session", "symbol", "session_ordinal"]],
        on=["session", "symbol"],
        how="left",
        validate="one_to_one",
    )
    if frame.session_ordinal.isna().any():
        raise ValueError("score rows lack current-session market data")
    lookup = bars.loc[:, ["symbol", "session_ordinal", "calc_close", "calc_open"]]
    for offset in (1, 2, 6, 21):
        future = lookup.copy()
        future["session_ordinal"] = future["session_ordinal"] - offset
        future = future.rename(
            columns={"calc_close": f"close_p{offset}", "calc_open": f"open_p{offset}"}
        )
        frame = frame.merge(
            future,
            on=["symbol", "session_ordinal"],
            how="left",
            validate="one_to_one",
        )
    frame["old_close_t2_over_t1"] = frame.close_p2 / frame.close_p1 - 1.0
    frame["open_to_open_1"] = frame.open_p2 / frame.open_p1 - 1.0
    frame["open_to_open_5"] = frame.open_p6 / frame.open_p1 - 1.0
    frame["open_to_open_20"] = frame.open_p21 / frame.open_p1 - 1.0
    summaries = {
        label: asdict(_summarize(frame, label))
        for label in (
            "old_close_t2_over_t1",
            "open_to_open_1",
            "open_to_open_5",
            "open_to_open_20",
        )
    }
    report: dict[str, object] = {
        "schema_version": 1,
        "SHADOW_SIGNAL_STATUS": "HISTORICAL_SIGNAL_DIAGNOSTICS_COMPLETE",
        "scores_sha256": _file_sha256(scores_path),
        "bars_sha256": _file_sha256(bars_path),
        "diagnostics_code_sha256": _file_sha256(Path(__file__)),
        "summaries": summaries,
        "limitations": [
            "historical final-revised development data",
            "old close label differs from actual T+1-open portfolio holding intervals",
            "signal metrics are separate from execution and cost-adjusted portfolio metrics",
        ],
    }
    encoded = canonical_json(report) + b"\n"
    path = output_root / "diagnostics" / f"{sha256(encoded).hexdigest()}.json"
    write_immutable(path, encoded)
    return path, report


def _summarize(frame: pd.DataFrame, label: str) -> HorizonSummary:
    valid = frame.loc[np.isfinite(frame[label]) & np.isfinite(frame.score)].copy()
    rows: list[dict[str, object]] = []
    for session, daily in valid.groupby("session", sort=True):
        if len(daily) < 20:
            continue
        label_rank = daily[label].rank(method="average")
        score_rank = daily.score.rank(method="average")
        top = daily.loc[daily.score_rank <= 20, label].mean()
        bottom = daily.loc[daily.score_rank > len(daily) - 20, label].mean()
        rows.append(
            {
                "session": pd.Timestamp(session),
                "ic": float(daily.score.corr(daily[label])),
                "rank_ic": float(score_rank.corr(label_rank)),
                "spread": float(top - bottom),
            }
        )
    daily = pd.DataFrame(rows).dropna()
    if daily.empty:
        raise ValueError(f"label {label} has no evaluable daily cross sections")
    yearly = daily.groupby(daily.session.dt.year).rank_ic.mean()
    return HorizonSummary(
        label=label,
        evaluated_rows=len(valid),
        evaluated_days=len(daily),
        mean_ic=float(daily.ic.mean()),
        mean_rank_ic=float(daily.rank_ic.mean()),
        rank_ic_newey_west_se_lag20=_newey_west_mean_se(daily.rank_ic.to_numpy(), 20),
        positive_rank_ic_day_fraction=float((daily.rank_ic > 0).mean()),
        mean_top20_minus_bottom20=float(daily.spread.mean()),
        yearly_rank_ic={str(year): float(value) for year, value in yearly.items()},
    )


def _newey_west_mean_se(values: np.ndarray, lag: int) -> float:
    centered = values.astype(float) - float(np.mean(values))
    size = len(centered)
    variance = float(centered @ centered) / size
    for offset in range(1, min(lag, size - 1) + 1):
        weight = 1.0 - offset / (lag + 1)
        covariance = float(centered[offset:] @ centered[:-offset]) / size
        variance += 2.0 * weight * covariance
    return math.sqrt(max(variance, 0.0) / size)


def _file_sha256(path: Path) -> str:
    digest = sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()
