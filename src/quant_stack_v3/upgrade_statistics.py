"""Paired robustness and bounded economic decisions for upgrade candidates."""

from __future__ import annotations

import math
from hashlib import sha256
from pathlib import Path

import numpy as np
import pandas as pd

from quant_stack.research_json import canonical_json
from quant_stack.snapshot import write_immutable
from quant_stack_v3.upgrade_protocol import CANDIDATE_IDS

BENCHMARKS = {
    candidate: "B100_LIQ100_D20" if candidate == "AF7_LOW_AVOID100_D20" else "B50_LIQ50_D20"
    for candidate in CANDIDATE_IDS
}


def select_scale_candidates(
    results: dict[str, dict[str, object]],
    artifact_root: Path,
) -> tuple[str, ...]:
    """Apply the preregistered, non-tuning scale-stress gate to at most two candidates."""
    qualified: list[tuple[float, str]] = []
    for candidate in CANDIDATE_IDS:
        benchmark = BENCHMARKS[candidate]
        result = results[f"{candidate}__REAL_T1_1M"]
        base = results[f"{benchmark}__REAL_T1_1M"]
        active_years = _active_years(result, base)
        active_cagr = _metric(result, "cagr") - _metric(base, "cagr")
        if (
            active_cagr > 0
            and _metric(result, "sharpe_ratio") >= _metric(base, "sharpe_ratio")
            and _metric(result, "maximum_drawdown") - _metric(base, "maximum_drawdown") >= -0.05
            and sum(value > 0 for value in active_years.values()) >= 7
        ):
            qualified.append((active_cagr, candidate))
    qualified.sort(key=lambda item: (-item[0], item[1]))
    return tuple(item[1] for item in qualified[:2])


def build_robustness_report(
    results: dict[str, dict[str, object]],
    artifact_root: Path,
    output_root: Path,
    *,
    replicates: int = 10_000,
    block_sessions: int = 21,
    seed: int = 20_260_922,
) -> tuple[Path, dict[str, object]]:
    """Bootstrap paired daily active returns and assign only frozen outcome classes."""
    if replicates != 10_000 or block_sessions != 21 or seed != 20_260_922:
        raise ValueError("upgrade robustness parameters are frozen")
    active_frames: dict[str, pd.Series] = {}
    observed: dict[str, float] = {}
    for candidate in CANDIDATE_IDS:
        benchmark = BENCHMARKS[candidate]
        candidate_nav = _nav(results[f"{candidate}__REAL_T1_1M"], artifact_root)
        benchmark_nav = _nav(results[f"{benchmark}__REAL_T1_1M"], artifact_root)
        joined = pd.concat(
            [np.log(candidate_nav).diff(), np.log(benchmark_nav).diff()], axis=1, join="inner"
        ).dropna()
        active = joined.iloc[:, 0] - joined.iloc[:, 1]
        active_frames[candidate] = active
        observed[candidate] = float(active.mean())
    common = sorted(set.intersection(*(set(value.index) for value in active_frames.values())))
    matrix = np.column_stack(
        [active_frames[candidate].loc[common].to_numpy(dtype=float) for candidate in CANDIDATE_IDS]
    )
    boot = _block_bootstrap_means(matrix, replicates, block_sessions, seed)
    p_values: dict[str, float] = {}
    intervals: dict[str, tuple[float, float]] = {}
    for column, candidate in enumerate(CANDIDATE_IDS):
        values = matrix[:, column]
        centered = values - values.mean()
        null_boot = _block_bootstrap_means(centered[:, None], replicates, block_sessions, seed)[
            :, 0
        ]
        p_values[candidate] = float(
            (1 + np.count_nonzero(null_boot >= observed[candidate])) / (replicates + 1)
        )
        intervals[candidate] = (
            float(np.quantile(boot[:, column], 0.025)),
            float(np.quantile(boot[:, column], 0.975)),
        )
    adjusted = _holm(p_values)
    rows: dict[str, object] = {}
    for candidate in CANDIDATE_IDS:
        benchmark = BENCHMARKS[candidate]
        real = results[f"{candidate}__REAL_T1_1M"]
        base_real = results[f"{benchmark}__REAL_T1_1M"]
        active_years = _active_years(real, base_real)
        active_cagr = _metric(real, "cagr") - _metric(base_real, "cagr")
        double_active = _metric(results[f"{candidate}__DOUBLE_ASSUMPTION_T1_1M"], "cagr") - _metric(
            results[f"{benchmark}__DOUBLE_ASSUMPTION_T1_1M"], "cagr"
        )
        t2_active = _metric(results[f"{candidate}__REAL_T2_1M"], "cagr") - _metric(
            results[f"{benchmark}__REAL_T2_1M"], "cagr"
        )
        drawdown_difference = _metric(real, "maximum_drawdown") - _metric(
            base_real, "maximum_drawdown"
        )
        valid = all(
            str(value.get("RESEARCH_VALIDITY", "")).startswith("VALID_")
            for value in (
                real,
                base_real,
                results[f"{candidate}__DOUBLE_ASSUMPTION_T1_1M"],
                results[f"{candidate}__REAL_T2_1M"],
            )
        )
        positive_years = sum(value > 0 for value in active_years.values())
        median_year = float(np.median(list(active_years.values())))
        retain = (
            valid
            and active_cagr > 0
            and adjusted[candidate] < 0.05
            and positive_years >= 7
            and median_year > 0
            and double_active >= 0
            and t2_active >= 0
            and drawdown_difference >= -0.05
        )
        outcome = (
            "NOT_EVALUABLE"
            if not valid
            else "RETAIN_FOR_PROSPECTIVE_VALIDATION_ONLY"
            if retain
            else "INCONCLUSIVE_HISTORICAL"
            if active_cagr > 0
            else "NO_HISTORICAL_EDGE"
        )
        rows[candidate] = {
            "benchmark": benchmark,
            "outcome": outcome,
            "active_cagr": active_cagr,
            "active_sharpe_difference": _metric(real, "sharpe_ratio")
            - _metric(base_real, "sharpe_ratio"),
            "maximum_drawdown_difference": drawdown_difference,
            "positive_active_years": positive_years,
            "median_active_year": median_year,
            "double_assumption_active_cagr": double_active,
            "t2_active_cagr": t2_active,
            "mean_daily_active_log_return": observed[candidate],
            "paired_block_bootstrap_95_interval": intervals[candidate],
            "one_sided_bootstrap_p": p_values[candidate],
            "holm_adjusted_p": adjusted[candidate],
        }
    report: dict[str, object] = {
        "schema_version": 1,
        "status": "PAIRED_ROBUSTNESS_COMPLETE",
        "replicates": replicates,
        "block_sessions": block_sessions,
        "seed": seed,
        "multiplicity": "Holm one-sided across eight preregistered candidates",
        "candidates": rows,
        "limitations": [
            "bootstrap reuses touched historical dates and is not new market evidence",
            "multiple seeds would measure computation, not independent markets",
        ],
    }
    encoded = canonical_json(report) + b"\n"
    path = output_root / "statistics" / f"{sha256(encoded).hexdigest()}.json"
    write_immutable(path, encoded)
    return path, report


def _block_bootstrap_means(
    values: np.ndarray, replicates: int, block: int, seed: int
) -> np.ndarray:
    rng = np.random.default_rng(seed)
    length = len(values)
    output = np.empty((replicates, values.shape[1]), dtype=float)
    block_offsets = np.arange(block)
    block_count = math.ceil(length / block)
    for replicate in range(replicates):
        starts = rng.integers(0, length, size=block_count)
        indexes = ((starts[:, None] + block_offsets) % length).reshape(-1)[:length]
        output[replicate] = values[indexes].mean(axis=0)
    return output


def _holm(p_values: dict[str, float]) -> dict[str, float]:
    ordered = sorted(p_values, key=lambda key: (p_values[key], key))
    adjusted: dict[str, float] = {}
    running = 0.0
    total = len(ordered)
    for index, key in enumerate(ordered):
        running = max(running, min(1.0, p_values[key] * (total - index)))
        adjusted[key] = running
    return adjusted


def _nav(result: dict[str, object], artifact_root: Path) -> pd.Series:
    path = artifact_root / "runs" / str(result["run_identity"]) / "nav.parquet"
    frame = pd.read_parquet(path)
    return pd.Series(
        frame.nav.astype(float).to_numpy(),
        index=pd.DatetimeIndex(frame.session),
        dtype=float,
    )


def _active_years(result: dict[str, object], benchmark: dict[str, object]) -> dict[str, float]:
    left = _mapping(result["calendar_year_returns"])
    right = _mapping(benchmark["calendar_year_returns"])
    return {
        year: _number(left[year]) - _number(right[year]) for year in sorted(set(left) & set(right))
    }


def _metric(result: dict[str, object], name: str) -> float:
    return _number(_mapping(result["metrics"])[name])


def _number(value: object) -> float:
    if not isinstance(value, (int, float, str)):
        raise ValueError("upgrade statistics metric must be numeric")
    return float(value)


def _mapping(value: object) -> dict[str, object]:
    if not isinstance(value, dict):
        raise ValueError("upgrade statistics field must be a mapping")
    return value
