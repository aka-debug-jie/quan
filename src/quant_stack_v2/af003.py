# ruff: noqa: I001, RUF001
"""AF-003 preregistered combination and fixed-model development diagnostics."""

from __future__ import annotations

import argparse
from datetime import date
from hashlib import sha256
from itertools import pairwise
from pathlib import Path
import json
import subprocess
from typing import Any, Literal, cast

import numpy as np
import pandas as pd
import yaml
from pydantic import Field, model_validator

from quant_stack_v2.af001 import _aggregate, _daily_metrics, load_registry as load_af001_registry
from quant_stack_v2.af002 import _blob, _mapping, _string
from quant_stack_v2.dev_contract import Digest, StrictModel, canonical, write_blob
from quant_stack_v2.dev_real_staged_view import (
    LABEL_COLUMN,
    load_features,
    load_staged_view,
    load_train_labels,
    load_validation_labels,
)

DEV001_SUMMARY_SHA256 = "606b072c361fd73f0da29d4ae4070dac31cf2e2a11f184be09fe929b06b13472"


class AF003Error(ValueError):
    """Raised when AF-003 would depart from its frozen limited-development scope."""


class Fold(StrictModel):
    """One chronological train/test fold with strictly prior training dates."""

    fold_id: Literal["AF003_2017", "AF003_2018", "AF003_2019", "AF003_2020"]
    train_start: date
    train_end: date
    test_start: date
    test_end: date

    @model_validator(mode="after")
    def chronological(self) -> Fold:
        if self.train_start > self.train_end or self.test_start > self.test_end:
            raise ValueError("AF-003 fold is reversed")
        if self.train_end >= self.test_start:
            raise ValueError("AF-003 training must precede its test fold")
        return self


class Selection(StrictModel):
    """Fixed model selection rules applied after all folds are retained."""

    baseline: Literal["equal_weight_zscore"]
    minimum_positive_increment_fold_fraction: float = Field(ge=0.0, le=1.0)
    require_positive_mean_increment: Literal[True]
    simple_rule: Literal["highest_mean_rank_ic_then_model_id"]
    challenger_rule: Literal["highest_mean_increment_then_model_id"]


class Registry(StrictModel):
    """Strict AF-003 preregistration bound to AF-002's exact output."""

    schema_version: Literal[1]
    registry_id: Literal["AF-003-CSI300-COMBINATIONS-V1"]
    status: Literal["PREREGISTERED"]
    scope: Literal["LIMITED_DEV_RESEARCH"]
    run_id: Literal["DEV-001"]
    universe: Literal["csi300"]
    required_af002_result_sha256: Digest
    candidate_alpha_ids: tuple[str, ...]
    label: Literal["close[T+2] / close[T+1] - 1"]
    folds: tuple[Fold, ...]
    preprocessing: Literal["train_fit_standard_scaler_complete_candidate_features"]
    simple_models: tuple[Literal["equal_weight_zscore", "train_rank_ic_weighted_zscore"], ...]
    models: dict[str, dict[str, Any]]
    tree_seeds: tuple[Literal[0, 1, 2], ...]
    selection: Selection
    missing_sensitivity: Literal["test_one_factor_at_a_time_replaced_with_training_mean"]
    forbidden_uses: tuple[str, ...]

    @model_validator(mode="after")
    def frozen(self) -> Registry:
        expected = (
            (
                "AF003_2017",
                date(2015, 1, 1),
                date(2016, 12, 31),
                date(2017, 1, 1),
                date(2017, 12, 31),
            ),
            (
                "AF003_2018",
                date(2015, 1, 1),
                date(2017, 12, 31),
                date(2018, 1, 1),
                date(2018, 12, 31),
            ),
            (
                "AF003_2019",
                date(2015, 1, 1),
                date(2018, 12, 31),
                date(2019, 1, 1),
                date(2019, 12, 31),
            ),
            (
                "AF003_2020",
                date(2015, 1, 1),
                date(2019, 12, 31),
                date(2020, 1, 1),
                date(2020, 12, 31),
            ),
        )
        actual = tuple(
            (f.fold_id, f.train_start, f.train_end, f.test_start, f.test_end) for f in self.folds
        )
        if actual != expected or len(self.candidate_alpha_ids) != 7:
            raise ValueError("AF-003 fold or candidate preregistration changed")
        if self.simple_models != ("equal_weight_zscore", "train_rank_ic_weighted_zscore"):
            raise ValueError("AF-003 simple-model order changed")
        if tuple(self.models) != ("ridge", "elasticnet", "lightgbm", "xgboost"):
            raise ValueError("AF-003 model order changed")
        if self.tree_seeds != (0, 1, 2):
            raise ValueError("AF-003 tree seed set changed")
        if self.forbidden_uses != (
            "csi500",
            "sealed_test",
            "portfolio_returns",
            "parameter_search",
            "promotion",
            "live_order",
            "network",
        ):
            raise ValueError("AF-003 forbidden-use boundary changed")
        return self


def load_registry(path: Path) -> Registry:
    """Load the immutable AF-003 configuration."""
    value = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise AF003Error("AF-003 registry must be a mapping")
    for key in ("candidate_alpha_ids", "folds", "simple_models", "tree_seeds", "forbidden_uses"):
        if not isinstance(value.get(key), list):
            raise AF003Error(f"AF-003 registry lacks list: {key}")
        value[key] = tuple(value[key])
    return Registry.model_validate(value)


def evaluate_frames(
    registry: Registry,
    features: pd.DataFrame,
    labels: pd.DataFrame,
    source: dict[str, tuple[str, int]],
) -> dict[str, object]:
    """Fit only within each fold's training range and preserve all model diagnostics."""
    _columns(features, ("session", "symbol", *[item[0] for item in source.values()]))
    joined = features.merge(labels, on=["session", "symbol"], how="left", validate="one_to_one")
    factors = pd.DataFrame(
        {alpha: sign * joined[field].astype(float) for alpha, (field, sign) in source.items()}
    )
    models = [*registry.simple_models, *registry.models]
    folds: list[dict[str, object]] = []
    results: dict[str, list[dict[str, object]]] = {model: [] for model in models}
    for fold in registry.folds:
        train_days = sorted(
            day
            for day in set(cast(list[date], joined["session"].tolist()))
            if fold.train_start <= day <= fold.train_end
        )
        if len(train_days) <= 2:
            raise AF003Error("AF-003 fold lacks two-session label purge")
        train_days = train_days[:-2]
        train_mask = joined["session"].isin(train_days)
        test_mask = (joined["session"] >= fold.test_start) & (joined["session"] <= fold.test_end)
        train_x, test_x = (
            factors.loc[train_mask].reset_index(drop=True),
            factors.loc[test_mask].reset_index(drop=True),
        )
        train_y = joined.loc[train_mask, LABEL_COLUMN].reset_index(drop=True)
        test_y = joined.loc[test_mask, LABEL_COLUMN].reset_index(drop=True)
        test_sessions = joined.loc[test_mask, "session"].reset_index(drop=True)
        valid_train = np.isfinite(train_y.to_numpy(dtype=float))
        if not valid_train.any() or test_x.empty:
            raise AF003Error("AF-003 fold has no train labels or test rows")
        train_sessions = joined.loc[train_mask, "session"].reset_index(drop=True)
        fold_models: dict[str, dict[str, object]] = {}
        fold_rows: dict[str, object] = {
            "fold_id": fold.fold_id,
            "resolved_train_signal_end": train_days[-1].isoformat(),
            "train_rows": int(valid_train.sum()),
            "test_rows": len(test_x),
            "models": fold_models,
        }
        simple_predictions = _simple_predictions(
            train_x.loc[valid_train],
            train_y.loc[valid_train],
            train_sessions.loc[valid_train],
            test_x,
            test_sessions,
        )
        baseline_rank: float | None = None
        for model in models:
            seed_diag: dict[str, object]
            if model in simple_predictions:
                prediction, importance, seed = simple_predictions[model]
                seed_diag = {"status": "NOT_APPLICABLE_DETERMINISTIC", "seeds": [seed]}
            else:
                prediction, importance, seed_diag = _model_predictions(
                    registry,
                    model,
                    train_x.loc[valid_train],
                    train_y.loc[valid_train],
                    test_x,
                    test_y,
                    test_sessions,
                )
            metrics = _metrics(test_sessions, test_y, prediction)
            if model == registry.selection.baseline:
                baseline_rank = _optional(metrics["daily_rank_ic"])
            missing = _missing_sensitivity(
                registry,
                model,
                train_x.loc[valid_train],
                train_y.loc[valid_train],
                train_sessions.loc[valid_train],
                test_x,
                test_y,
                test_sessions,
            )
            record: dict[str, object] = {
                "model_id": model,
                "metrics": metrics,
                "importance": importance,
                "seed_stability": seed_diag,
                "missing_sensitivity": missing,
            }
            fold_models[model] = record
            results[model].append(record)
        if baseline_rank is None:
            raise AF003Error("AF-003 baseline has undefined Rank IC")
        for record in fold_models.values():
            rank_ic = _optional(_mapping(record, "metrics")["daily_rank_ic"])
            record["rank_ic_increment_vs_equal_weight"] = (
                rank_ic - baseline_rank if rank_ic is not None else None
            )
        folds.append(fold_rows)
    summary = {model: _model_summary(rows, registry.folds) for model, rows in results.items()}
    simple = max(
        registry.simple_models, key=lambda model: (_number(summary[model]["mean_rank_ic"]), model)
    )
    challenger = _challenger(registry, results, simple)
    return {
        "schema_version": 1,
        "kind": "af003_combination_diagnostics",
        "status": "AF003_COMPLETED_LIMITED_DEV_DIAGNOSTICS",
        "folds": folds,
        "models": summary,
        "selected_simple_model": simple,
        "selected_ml_challenger": challenger,
        "formal_pit_status": "BLOCKED_DATA",
        "formal_research_status": "BLOCKED_DATA",
        "csi500": "NOT_STARTED",
    }


def run_af003(development_root: Path, repo_root: Path, registry_path: Path) -> dict[str, object]:
    """Open only approved inputs and bind their content identities to AF-003 output."""
    registry = load_registry(registry_path)
    summary = _blob(development_root / "dev001" / "summaries", DEV001_SUMMARY_SHA256)
    identities = _mapping(summary, "identities")
    af002 = _blob(development_root / "af002" / "results", registry.required_af002_result_sha256)
    if (
        summary.get("status") != "DEV_REAL_RUN_COMPLETED"
        or summary.get("formal_research") != "BLOCKED_DATA"
        or summary.get("csi500") != "NOT_STARTED"
        or af002.get("status") != "AF002_COMPLETED_LIMITED_DEV_DIAGNOSTICS"
        or af002.get("formal_research_status") != "BLOCKED_DATA"
        or af002.get("csi500") != "NOT_STARTED"
        or af002.get("selected_count") != len(registry.candidate_alpha_ids)
    ):
        raise AF003Error("DEV-001 or AF-002 input is not completed")
    selected = af002.get("selected_alpha_ids")
    if (
        not isinstance(selected, list)
        or tuple(cast(list[str], selected)) != registry.candidate_alpha_ids
    ):
        raise AF003Error("AF-002 candidates differ from AF-003 preregistration")
    view = load_staged_view(
        development_root / "dev001" / "authority",
        development_root / "dev001" / "views",
        _string(identities, "contract_sha256"),
        _string(identities, "evidence_sha256"),
        _string(identities, "view_pin_sha256"),
    )
    if (
        view.contract.formal_qualification != "BLOCKED_DATA"
        or view.contract.sealed_test != "NOT_STARTED"
    ):
        raise AF003Error("view formal status changed")
    registry_af001 = load_af001_registry(
        repo_root / "configs/v2/alphas/af_001_alpha_registry_v1.yaml"
    )
    all_definitions = {
        item.alpha_id: (item.source_feature, item.multiplier) for item in registry_af001.alphas
    }
    if not set(registry.candidate_alpha_ids) <= set(all_definitions):
        raise AF003Error("AF-003 source formulas differ from frozen candidates")
    definitions: dict[str, tuple[str, int]] = {
        alpha: (all_definitions[alpha][0], int(all_definitions[alpha][1]))
        for alpha in registry.candidate_alpha_ids
    }
    features = pd.concat(
        [load_features(view, "train"), load_features(view, "validation")], ignore_index=True
    )
    labels = pd.concat(
        [
            load_train_labels(view),
            load_validation_labels(
                view,
                development_root / "dev001" / "views",
                _string(identities, "validation_target_sha256"),
            ),
        ],
        ignore_index=True,
    )
    payload = evaluate_frames(registry, features, labels, definitions)
    payload["provenance"] = {
        "af003_registry_sha256": sha256(registry_path.read_bytes()).hexdigest(),
        "af002_result_sha256": registry.required_af002_result_sha256,
        "dev001_summary_sha256": DEV001_SUMMARY_SHA256,
        "contract_sha256": _string(identities, "contract_sha256"),
        "evidence_sha256": _string(identities, "evidence_sha256"),
        "view_sha256": view.manifest_sha256,
        "validation_target_sha256": _string(identities, "validation_target_sha256"),
        "calendar_sha256": view.contract.calendar_sha256,
        "code_sha256": sha256((repo_root / "src/quant_stack_v2/af003.py").read_bytes()).hexdigest(),
        "git_commit": _commit(repo_root),
    }
    return payload


def _simple_predictions(
    train_x: pd.DataFrame,
    train_y: pd.Series,
    train_sessions: pd.Series,
    test_x: pd.DataFrame,
    test_sessions: pd.Series,
) -> dict[str, tuple[np.ndarray, dict[str, float], int]]:
    equal = _daily_z(test_x, test_sessions).mean(axis=1).to_numpy(dtype=float)
    weights: dict[str, float] = {}
    for field in train_x.columns:
        rows = pd.DataFrame(
            {"session": train_sessions, "score": train_x[field], LABEL_COLUMN: train_y}
        )
        daily = _daily_metrics(rows, 2)
        weights[field] = float(np.mean([item.rank_ic for item in daily])) if daily else 0.0
    weight_series = pd.Series(weights)
    if float(weight_series.abs().sum()) == 0:
        raise AF003Error("training Rank-IC weights are all zero")
    weight_series = weight_series / weight_series.abs().sum()
    return {
        "equal_weight_zscore": (
            equal,
            {str(field): 1 / len(weight_series) for field in weight_series.index},
            0,
        ),
        "train_rank_ic_weighted_zscore": (
            (_daily_z(test_x, test_sessions) @ weight_series).to_numpy(dtype=float),
            {str(field): float(value) for field, value in weight_series.items()},
            0,
        ),
    }


def _model_predictions(
    registry: Registry,
    model_id: str,
    train_x: pd.DataFrame,
    train_y: pd.Series,
    test_x: pd.DataFrame,
    test_y: pd.Series,
    sessions: pd.Series,
) -> tuple[np.ndarray, dict[str, float], dict[str, object]]:
    from sklearn.preprocessing import StandardScaler  # type: ignore[import-untyped]

    scaler = StandardScaler(copy=True, with_mean=True, with_std=True).set_output(transform="pandas")
    scaler.fit(train_x)
    fitted: list[tuple[np.ndarray, dict[str, float]]] = []
    seeds = registry.tree_seeds if model_id in {"lightgbm", "xgboost"} else (0,)
    for seed in seeds:
        model = _estimator(registry, model_id, seed)
        model.fit(scaler.transform(train_x), train_y.to_numpy(dtype=float))
        values = np.asarray(model.predict(scaler.transform(test_x)), dtype=float)
        importance = _importance(model, train_x.columns)
        fitted.append((values, importance))
    predictions = fitted[0][0]
    rank_values = [
        _optional(_metrics(sessions, test_y, value)["daily_rank_ic"]) for value, _ in fitted
    ]
    return (
        predictions,
        fitted[0][1],
        {
            "status": "FIXED_SEEDS",
            "seeds": list(seeds),
            "rank_ic_by_seed": rank_values,
            "worst_seed_rank_ic": min(
                cast(list[float], [item for item in rank_values if item is not None]), default=None
            ),
            "importance_seed_range": _importance_range([item[1] for item in fitted]),
        },
    )


def _estimator(registry: Registry, model_id: str, seed: int) -> Any:
    params = dict(registry.models[model_id])
    if model_id == "ridge":
        from sklearn.linear_model import Ridge  # type: ignore[import-untyped]

        return Ridge(**params)
    if model_id == "elasticnet":
        from sklearn.linear_model import ElasticNet

        return ElasticNet(**params)
    if model_id == "lightgbm":
        from lightgbm import LGBMRegressor

        return LGBMRegressor(**params, random_state=seed)
    from xgboost import XGBRegressor

    return XGBRegressor(**params, random_state=seed)


def _daily_z(frame: pd.DataFrame, sessions: pd.Series) -> pd.DataFrame:
    """Z-score each candidate factor across the same-day cross section only."""
    output = frame.copy()
    for _, positions in sessions.groupby(sessions, sort=True).groups.items():
        rows = list(positions)
        subset = output.iloc[rows]
        deviation = subset.std(axis=0, ddof=0).replace(0.0, np.nan)
        output.iloc[rows] = (
            subset.sub(subset.mean(axis=0), axis=1).div(deviation, axis=1).fillna(0.0)
        )
    return output


def _metrics(sessions: pd.Series, labels: pd.Series, predictions: np.ndarray) -> dict[str, object]:
    frame = pd.DataFrame({"session": sessions, "score": predictions, LABEL_COLUMN: labels})
    valid = frame[np.isfinite(frame["score"]) & np.isfinite(frame[LABEL_COLUMN])]
    daily = _daily_metrics(valid, 2)
    return _aggregate(daily) | {"evaluated_rows": len(valid)}


def _missing_sensitivity(
    registry: Registry,
    model_id: str,
    train_x: pd.DataFrame,
    train_y: pd.Series,
    train_sessions: pd.Series,
    test_x: pd.DataFrame,
    test_y: pd.Series,
    sessions: pd.Series,
) -> dict[str, object]:
    base = (
        _simple_predictions(train_x, train_y, train_sessions, test_x, sessions)[model_id][0]
        if model_id in registry.simple_models
        else _model_predictions(registry, model_id, train_x, train_y, test_x, test_y, sessions)[0]
    )
    base_rank = _optional(_metrics(sessions, test_y, base)["daily_rank_ic"])
    rows: list[dict[str, object]] = []
    for field in test_x.columns:
        stressed = test_x.copy()
        stressed[field] = float(train_x[field].mean())
        prediction = (
            _simple_predictions(train_x, train_y, train_sessions, stressed, sessions)[model_id][0]
            if model_id in registry.simple_models
            else _model_predictions(
                registry, model_id, train_x, train_y, stressed, test_y, sessions
            )[0]
        )
        rank = _optional(_metrics(sessions, test_y, prediction)["daily_rank_ic"])
        rows.append(
            {
                "factor": field,
                "stressed_rank_ic": rank,
                "delta": rank - base_rank if rank is not None and base_rank is not None else None,
            }
        )
    return {"status": registry.missing_sensitivity, "baseline_rank_ic": base_rank, "factors": rows}


def _importance(model: Any, columns: pd.Index) -> dict[str, float]:
    value = getattr(model, "feature_importances_", getattr(model, "coef_", np.zeros(len(columns))))
    numbers = np.abs(np.asarray(value, dtype=float).reshape(-1))
    total = float(numbers.sum())
    return {
        str(key): float(item / total) if total else 0.0
        for key, item in zip(cast(list[str], columns.tolist()), numbers, strict=True)
    }


def _importance_range(values: list[dict[str, float]]) -> float:
    return float(max(max(item.values()) - min(item.values()) for item in values)) if values else 0.0


def _model_summary(rows: list[dict[str, object]], folds: tuple[Fold, ...]) -> dict[str, object]:
    rank = [_optional(_mapping(row, "metrics")["daily_rank_ic"]) for row in rows]
    increments = [cast(float | None, row.get("rank_ic_increment_vs_equal_weight")) for row in rows]
    finite_rank = [item for item in rank if item is not None]
    finite_increment = [item for item in increments if item is not None]
    worst_rank_index = min(
        range(len(rank)), key=lambda index: (rank[index] is None, rank[index] or 0.0)
    )
    worst_increment_index = min(
        range(len(increments)),
        key=lambda index: (increments[index] is None, increments[index] or 0.0),
    )
    importances = [cast(dict[str, float], row["importance"]) for row in rows]
    drift = [
        float(sum(abs(current[key] - previous[key]) for key in current))
        for previous, current in pairwise(importances)
    ]
    return {
        "mean_rank_ic": float(np.mean([item for item in rank if item is not None]))
        if any(item is not None for item in rank)
        else None,
        "worst_fold_rank_ic": min(finite_rank, default=None),
        "worst_fold_rank_ic_id": folds[worst_rank_index].fold_id if finite_rank else None,
        "mean_increment_vs_equal_weight": float(np.mean(finite_increment))
        if finite_increment
        else None,
        "positive_increment_fold_fraction": float(np.mean([item > 0 for item in finite_increment]))
        if finite_increment
        else None,
        "worst_increment_fold_id": folds[worst_increment_index].fold_id
        if finite_increment
        else None,
        "feature_importance_l1_drift_by_adjacent_fold": drift,
        "max_feature_importance_l1_drift": max(drift, default=None),
    }


def _challenger(
    registry: Registry, results: dict[str, list[dict[str, object]]], simple: str
) -> str:
    baseline = [_optional(_mapping(row, "metrics")["daily_rank_ic"]) for row in results[simple]]
    qualified: list[tuple[float, str]] = []
    for model in registry.models:
        values = [_optional(_mapping(row, "metrics")["daily_rank_ic"]) for row in results[model]]
        increments = [
            value - reference
            for value, reference in zip(values, baseline, strict=True)
            if value is not None and reference is not None
        ]
        if (
            len(increments) == len(registry.folds)
            and float(np.mean(increments)) > 0
            and float(np.mean(np.asarray(increments) > 0))
            >= registry.selection.minimum_positive_increment_fold_fraction
        ):
            qualified.append((float(np.mean(increments)), model))
    return max(qualified)[1] if qualified else "NO_STABLE_ML_INCREMENT"


def _columns(frame: pd.DataFrame, names: tuple[str, ...]) -> None:
    if not set(names) <= set(frame.columns):
        raise AF003Error("AF-003 feature schema is incomplete")


def _optional(value: object) -> float | None:
    return float(value) if isinstance(value, (int, float)) and not isinstance(value, bool) else None


def _number(value: object) -> float:
    if value is None:
        raise AF003Error("required model metric is undefined")
    return float(cast(float, value))


def _commit(root: Path) -> str:
    return subprocess.run(
        ["git", "-C", str(root), "rev-parse", "HEAD"], check=True, capture_output=True, text=True
    ).stdout.strip()


def persist(payload: dict[str, object], root: Path) -> str:
    """Write a content-addressed AF-003 result without replacing prior output."""
    return write_blob(root / "results", canonical(payload))


def main() -> None:
    """Run AF-003 through the restricted development root."""
    parser = argparse.ArgumentParser()
    parser.add_argument("--development-root", type=Path, required=True)
    parser.add_argument("--repo-root", type=Path, required=True)
    parser.add_argument("--registry", type=Path, required=True)
    parser.add_argument("--result-root", type=Path, required=True)
    parser.add_argument("--report", type=Path, required=True)
    args = parser.parse_args()
    payload = run_af003(args.development_root, args.repo_root, args.registry)
    identity = persist(payload, args.result_root)
    args.report.write_text(
        f"# AF-003：简单组合与机器学习增量诊断\n\n"
        f"状态：`{payload['status']}`；结果 identity：`{identity}`。\n\n"
        f"- 简单组合：`{payload['selected_simple_model']}`。\n"
        f"- 机器学习 challenger：`{payload['selected_ml_challenger']}`。\n"
        f"- 不含组合收益、CAGR、Sharpe、CSI500 或正式资格结论。\n\n"
        f"`FORMAL_PIT_STATUS=BLOCKED_DATA`、"
        f"`FORMAL_RESEARCH_STATUS=BLOCKED_DATA`、`CSI500=NOT_STARTED` 保持不变。\n",
        encoding="utf-8",
    )
    print(json.dumps({"status": payload["status"], "result_sha256": identity}, sort_keys=True))


if __name__ == "__main__":
    main()
