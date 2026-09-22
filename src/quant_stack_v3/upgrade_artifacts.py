"""Immutable score and measurement artifacts for the research upgrade."""

from __future__ import annotations

import os
import tempfile
from hashlib import sha256
from pathlib import Path

import numpy as np
import pandas as pd

from quant_stack.research_json import canonical_json
from quant_stack.snapshot import write_immutable
from quant_stack_v3.upgrade_diagnostics import summarize_fixed_pools
from quant_stack_v3.upgrade_signals import build_upgrade_signals, residualize_scores

_ATTRIBUTION_SIGNALS = {
    "AF7": ("score", "score_rank"),
    "AF7_RESIDUAL": ("residual_score", "residual_rank"),
    "MOM_60_5": ("MOM_60_5_score", "MOM_60_5_rank"),
    "COND_REV_5": ("COND_REV_5_score", "COND_REV_5_rank"),
    "DOWNSIDE_60": ("DOWNSIDE_60_score", "DOWNSIDE_60_rank"),
    "ROBUST_TREND": ("ROBUST_TREND_score", "ROBUST_TREND_rank"),
}


def build_upgrade_score_cache(
    bars_path: Path,
    base_scores_path: Path,
    output_root: Path,
) -> tuple[Path, Path, dict[str, object]]:
    """Add preregistered signals and exposure residuals to the frozen AF7 rows."""
    bars = pd.read_parquet(bars_path)
    base = pd.read_parquet(base_scores_path)
    upgraded = build_upgrade_signals(bars, base.loc[:, ["session", "symbol"]])
    additions = upgraded.drop(
        columns=[
            name
            for name in upgraded.columns
            if name in {"session", "symbol"} or name in base.columns
        ],
        errors="ignore",
    )
    additions.insert(0, "symbol", upgraded["symbol"])
    additions.insert(0, "session", upgraded["session"])
    combined = base.merge(
        additions,
        on=["session", "symbol"],
        how="left",
        validate="one_to_one",
    ).sort_values(["session", "score_rank", "symbol"], kind="stable")
    residual = residualize_scores(
        combined.loc[
            :,
            ["session", "symbol", "score", "beta60", "vol60", "log_amount60"],
        ]
    ).loc[:, ["session", "symbol", "residual_score", "residual_rank"]]
    combined = combined.merge(residual, on=["session", "symbol"], how="left", validate="one_to_one")
    output_root.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=".upgrade-scores-", suffix=".parquet", dir=output_root
    )
    os.close(descriptor)
    temporary = Path(temporary_name)
    try:
        combined.to_parquet(temporary, index=False, compression="zstd")
        digest = _file_sha256(temporary)
        destination = output_root / "signals" / digest / "scores.parquet"
        destination.parent.mkdir(parents=True, exist_ok=True)
        if destination.exists():
            if _file_sha256(destination) != digest:
                raise ValueError("upgrade score cache conflicts with content identity")
        else:
            temporary.replace(destination)
    finally:
        temporary.unlink(missing_ok=True)
    report: dict[str, object] = {
        "schema_version": 1,
        "status": "UPGRADE_SIGNALS_COMPLETE",
        "bars_sha256": _file_sha256(bars_path),
        "base_scores_sha256": _file_sha256(base_scores_path),
        "scores_sha256": digest,
        "rows": len(combined),
        "sessions": int(combined.session.nunique()),
        "symbols": int(combined.symbol.nunique()),
        "valid_sessions": {
            column: int(
                combined.groupby("session")[column].apply(lambda values: values.notna().any()).sum()
            )
            for column in (
                "MOM_60_5_rank",
                "COND_REV_5_rank",
                "DOWNSIDE_60_rank",
                "ROBUST_TREND_rank",
                "residual_rank",
            )
        },
    }
    encoded = canonical_json(report) + b"\n"
    report_path = output_root / "signals" / digest / "report.json"
    write_immutable(report_path, encoded)
    return destination, report_path, report


def build_measurement_audit(
    bars_path: Path,
    scores_path: Path,
    output_root: Path,
) -> tuple[Path, dict[str, object]]:
    """Publish old-versus-fixed group evidence for all four frozen labels."""
    scores = pd.read_parquet(scores_path)
    bars = pd.read_parquet(
        bars_path,
        columns=["session", "symbol", "session_ordinal", "calc_close", "calc_open"],
    )
    frame = scores.loc[:, ["session", "symbol", "score", "score_rank"]].merge(
        bars.loc[:, ["session", "symbol", "session_ordinal"]],
        on=["session", "symbol"],
        how="left",
        validate="one_to_one",
    )
    lookup = bars.loc[:, ["symbol", "session_ordinal", "calc_close", "calc_open"]]
    for offset in (1, 2, 6, 21):
        future = lookup.copy()
        future["session_ordinal"] -= offset
        future = future.rename(
            columns={"calc_close": f"close_p{offset}", "calc_open": f"open_p{offset}"}
        )
        frame = frame.merge(
            future,
            on=["symbol", "session_ordinal"],
            how="left",
            validate="one_to_one",
        )
    labels = pd.DataFrame(
        {
            "session": frame.session,
            "symbol": frame.symbol,
            "old_close_t2_over_t1": frame.close_p2 / frame.close_p1 - 1.0,
            "open_to_open_1": frame.open_p2 / frame.open_p1 - 1.0,
            "open_to_open_5": frame.open_p6 / frame.open_p1 - 1.0,
            "open_to_open_20": frame.open_p21 / frame.open_p1 - 1.0,
        }
    )
    summaries: dict[str, object] = {}
    for label in labels.columns[2:]:
        daily = summarize_fixed_pools(scores, labels, str(label))
        summaries[str(label)] = {
            "days": len(daily),
            "days_with_any_missing_label": int((daily.pool_coverage < 1).sum()),
            "days_with_incomplete_top": int((daily.top_coverage < 1).sum()),
            "days_with_incomplete_bottom": int((daily.bottom_coverage < 1).sum()),
            "mean_top": _finite_mean(daily.top_mean),
            "mean_pool": _finite_mean(daily.pool_mean),
            "mean_bottom": _finite_mean(daily.bottom_mean),
            "mean_top_minus_pool": _finite_mean(daily.top_minus_pool),
            "mean_pool_minus_bottom": _finite_mean(daily.pool_minus_bottom),
            "mean_fixed_top_minus_bottom": _finite_mean(daily.top_minus_bottom),
            "mean_legacy_top_minus_bottom": _finite_mean(daily.legacy_top_minus_bottom),
            "mean_fixed_minus_legacy": _finite_mean(daily.fixed_minus_legacy_spread),
        }
    report: dict[str, object] = {
        "schema_version": 1,
        "status": "MEASUREMENT_BOUNDARY_AUDIT_COMPLETE",
        "bars_sha256": _file_sha256(bars_path),
        "scores_sha256": _file_sha256(scores_path),
        "summaries": summaries,
    }
    encoded = canonical_json(report) + b"\n"
    path = output_root / "measurement" / f"{sha256(encoded).hexdigest()}.json"
    write_immutable(path, encoded)
    return path, report


def build_signal_attribution(
    bars_path: Path,
    scores_path: Path,
    output_root: Path,
) -> tuple[Path, dict[str, object]]:
    """Decompose selection, avoidance, risk exposures and rank persistence."""
    scores = pd.read_parquet(scores_path)
    bars = pd.read_parquet(
        bars_path,
        columns=["session", "symbol", "session_ordinal", "calc_open"],
    )
    frame = scores.copy()
    if "session_ordinal" not in frame.columns:
        frame = frame.merge(
            bars.loc[:, ["session", "symbol", "session_ordinal"]],
            on=["session", "symbol"],
            how="left",
            validate="one_to_one",
        )
    lookup = bars.loc[:, ["symbol", "session_ordinal", "calc_open"]]
    labels = frame.loc[:, ["session", "symbol"]].copy()
    for horizon, offset in ((1, 2), (5, 6), (20, 21)):
        entry = lookup.copy()
        entry["session_ordinal"] -= 1
        entry = entry.rename(columns={"calc_open": "entry_open"})
        exit_frame = lookup.copy()
        exit_frame["session_ordinal"] -= offset
        exit_frame = exit_frame.rename(columns={"calc_open": "exit_open"})
        paired = frame.loc[:, ["session", "symbol", "session_ordinal"]].merge(
            entry,
            on=["symbol", "session_ordinal"],
            how="left",
            validate="one_to_one",
        )
        paired = paired.merge(
            exit_frame,
            on=["symbol", "session_ordinal"],
            how="left",
            validate="one_to_one",
        )
        labels[f"open_to_open_{horizon}"] = paired.exit_open / paired.entry_open - 1.0
    output: dict[str, object] = {}
    for signal, (score_column, rank_column) in _ATTRIBUTION_SIGNALS.items():
        available = frame.loc[
            np.isfinite(frame[score_column]) & np.isfinite(frame[rank_column])
        ].copy()
        fixed_scores = available.loc[
            :, ["session", "symbol", "session_ordinal", score_column, rank_column]
        ].rename(columns={score_column: "score", rank_column: "score_rank"})
        label_summaries: dict[str, object] = {}
        for label in ("open_to_open_1", "open_to_open_5", "open_to_open_20"):
            daily = summarize_fixed_pools(fixed_scores, labels, label)
            label_summaries[label] = {
                "sessions": len(daily),
                "mean_pool_coverage": float(daily.pool_coverage.mean()),
                "incomplete_top_sessions": int((daily.top_coverage < 1).sum()),
                "incomplete_bottom_sessions": int((daily.bottom_coverage < 1).sum()),
                "mean_top": _finite_mean(daily.top_mean),
                "mean_pool": _finite_mean(daily.pool_mean),
                "mean_bottom": _finite_mean(daily.bottom_mean),
                "mean_top_minus_pool": _finite_mean(daily.top_minus_pool),
                "mean_pool_minus_bottom": _finite_mean(daily.pool_minus_bottom),
                "mean_top_minus_bottom": _finite_mean(daily.top_minus_bottom),
            }
        risk = _risk_attribution(available, score_column, rank_column)
        persistence = _rank_persistence(fixed_scores)
        output[signal] = {
            "score_column": score_column,
            "rank_column": rank_column,
            "sessions": int(available.session.nunique()),
            "rows": len(available),
            "labels": label_summaries,
            "risk_exposures": risk,
            "persistence": persistence,
        }
    report: dict[str, object] = {
        "schema_version": 1,
        "status": "SIGNAL_SOURCE_ATTRIBUTION_COMPLETE",
        "bars_sha256": _file_sha256(bars_path),
        "scores_sha256": _file_sha256(scores_path),
        "signals": output,
        "not_evaluated": [
            "PIT industry exposure",
            "PIT market capitalization or shares outstanding",
        ],
        "limitations": [
            "amount is a liquidity proxy and is not market capitalization",
            "top-minus-bottom is a statistical diagnostic, not an executable short portfolio",
            "residualization overlap does not prove the raw mechanism is spurious",
        ],
    }
    encoded = canonical_json(report) + b"\n"
    path = output_root / "attribution" / f"{sha256(encoded).hexdigest()}.json"
    write_immutable(path, encoded)
    return path, report


def _risk_attribution(
    frame: pd.DataFrame, score_column: str, rank_column: str
) -> dict[str, object]:
    output: dict[str, object] = {}
    for exposure in ("beta60", "vol60", "log_amount60"):
        daily_corr: list[float] = []
        top_minus_pool: list[float] = []
        for _, day in frame.groupby("session", sort=True):
            valid = day.loc[np.isfinite(day[exposure])]
            if len(valid) < 20:
                continue
            correlation = valid[score_column].corr(valid[exposure])
            if np.isfinite(correlation):
                daily_corr.append(float(correlation))
            top = valid.loc[valid[rank_column] <= 20, exposure]
            if len(top):
                top_minus_pool.append(float(top.mean() - valid[exposure].mean()))
        output[exposure] = {
            "mean_daily_score_correlation": float(np.mean(daily_corr)) if daily_corr else None,
            "mean_top20_minus_pool_exposure": float(np.mean(top_minus_pool))
            if top_minus_pool
            else None,
            "evaluated_sessions": len(daily_corr),
        }
    return output


def _rank_persistence(scores: pd.DataFrame) -> dict[str, object]:
    output: dict[str, object] = {}
    for horizon in (1, 5, 20):
        future = scores.loc[:, ["symbol", "session_ordinal", "score_rank"]].copy()
        future["session_ordinal"] -= horizon
        future = future.rename(columns={"score_rank": "future_rank"})
        joined = scores.merge(
            future,
            on=["symbol", "session_ordinal"],
            how="left",
            validate="one_to_one",
        )
        correlations: list[float] = []
        survival20: list[float] = []
        survival50: list[float] = []
        for _, day in joined.groupby("session", sort=True):
            valid = day.loc[np.isfinite(day.future_rank)]
            if len(valid) < 20:
                continue
            correlation = valid.score_rank.corr(valid.future_rank)
            if np.isfinite(correlation):
                correlations.append(float(correlation))
            for size, values in ((20, survival20), (50, survival50)):
                current = day.loc[day.score_rank <= size]
                if len(current) == size:
                    values.append(float((current.future_rank <= size).sum() / size))
        output[str(horizon)] = {
            "mean_rank_correlation": float(np.mean(correlations)) if correlations else None,
            "mean_top20_survival": float(np.mean(survival20)) if survival20 else None,
            "mean_top50_survival": float(np.mean(survival50)) if survival50 else None,
            "evaluated_sessions": len(correlations),
        }
    return output


def _finite_mean(values: pd.Series) -> float | None:
    finite = values.loc[np.isfinite(values)]
    return float(finite.mean()) if len(finite) else None


def _file_sha256(path: Path) -> str:
    digest = sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()
