# ruff: noqa: RUF001
"""AF-002 fixed walk-forward stability and redundancy diagnostics."""

from __future__ import annotations

import argparse
import json
import math
import subprocess
from dataclasses import asdict, dataclass
from datetime import date
from hashlib import sha256
from pathlib import Path
from typing import Literal, cast

import numpy as np
import pandas as pd
import yaml
from pydantic import Field, model_validator

from quant_stack_v2.af001 import AlphaRegistry, DailyMetric, _aggregate, _daily_metrics
from quant_stack_v2.dev_contract import Digest, StrictModel, canonical, read_blob, write_blob
from quant_stack_v2.dev_real_staged_view import (
    LABEL_COLUMN,
    load_features,
    load_staged_view,
    load_train_labels,
    load_validation_labels,
)

DEV001_SUMMARY_SHA256 = "606b072c361fd73f0da29d4ae4070dac31cf2e2a11f184be09fe929b06b13472"


class AF002Error(ValueError):
    """Raised when an AF-002 input is outside its frozen limited-development scope."""


class Fold(StrictModel):
    """One fixed, chronological development evaluation interval."""

    fold_id: Literal["WF_2017", "WF_2018", "WF_2019", "WF_2020"]
    start: date
    end: date

    @model_validator(mode="after")
    def ordered(self) -> Fold:
        if self.start > self.end:
            raise ValueError("AF-002 fold is reversed")
        return self


class StabilityRule(StrictModel):
    """Frozen factor stability rule applied before redundancy pruning."""

    minimum_defined_days_per_fold: int = Field(ge=1)
    minimum_evaluation_coverage: float = Field(ge=0.0, le=1.0)
    minimum_positive_fold_fraction: float = Field(ge=0.0, le=1.0)
    require_positive_mean_rank_ic: Literal[True]


class RedundancyRule(StrictModel):
    """Frozen relation thresholds and deterministic cluster representative rule."""

    absolute_value_correlation_threshold: float = Field(ge=0.0, le=1.0)
    absolute_ic_correlation_threshold: float = Field(ge=0.0, le=1.0)
    top_score_fraction: float = Field(gt=0.0, le=1.0)
    top_score_proxy_overlap_threshold: float = Field(ge=0.0, le=1.0)
    representative_rule: Literal["highest_mean_rank_ic_then_alpha_id"]
    maximum_candidates: int = Field(ge=1, le=8)
    value_correlation: Literal["mean_daily_pearson_absolute"]
    ic_correlation: Literal["pearson_of_aligned_daily_ic_absolute"]
    rank_ic_correlation: Literal["pearson_of_aligned_daily_rank_ic_absolute"]
    top_score_proxy: Literal["daily_top_fraction_jaccard_keep_all_ties"]
    clustering: Literal["connected_components_any_threshold_or_undefined"]
    undefined_relation_is_redundant: Literal[True]


class ExposureRule(StrictModel):
    """Declare diagnostics unavailable from the approved Alpha158-only view."""

    industry: Literal["NOT_AVAILABLE_IN_APPROVED_VIEW"]
    market_cap: Literal["NOT_AVAILABLE_IN_APPROVED_VIEW"]


class AF002Registry(StrictModel):
    """Versioned AF-002 preregistration bound to frozen AF-001 identities."""

    schema_version: Literal[1]
    registry_id: Literal["AF-002-CSI300-WALK-FORWARD-V1"]
    status: Literal["PREREGISTERED"]
    scope: Literal["LIMITED_DEV_RESEARCH"]
    run_id: Literal["DEV-001"]
    universe: Literal["csi300"]
    required_af001_registry_sha256: Digest
    required_af001_result_sha256: Digest
    label: Literal["close[T+2] / close[T+1] - 1"]
    folds: tuple[Fold, ...]
    stability: StabilityRule
    redundancy: RedundancyRule
    exposure_diagnostics: ExposureRule
    forbidden_uses: tuple[str, ...]

    @model_validator(mode="after")
    def complete_preregistration(self) -> AF002Registry:
        expected_folds = (
            ("WF_2017", date(2017, 1, 1), date(2017, 12, 31)),
            ("WF_2018", date(2018, 1, 1), date(2018, 12, 31)),
            ("WF_2019", date(2019, 1, 1), date(2019, 12, 31)),
            ("WF_2020", date(2020, 1, 1), date(2020, 12, 31)),
        )
        if tuple((fold.fold_id, fold.start, fold.end) for fold in self.folds) != expected_folds:
            raise ValueError("AF-002 requires exactly the four fixed annual folds")
        if self.forbidden_uses != (
            "csi500",
            "sealed_test",
            "portfolio_returns",
            "parameter_search",
            "promotion",
            "live_order",
            "network",
        ):
            raise ValueError("AF-002 forbidden-use boundary changed")
        return self


@dataclass(frozen=True)
class FoldMetric:
    """One factor's metric record for one fixed walk-forward fold."""

    fold_id: str
    input_rows: int
    evaluated_rows: int
    published_view_evaluation_coverage: float
    within_view_feature_missing_rows: int
    label_missing_rows: int
    metrics: dict[str, object]
    industry_exposure: str
    market_cap_exposure: str


def load_registry(path: Path) -> AF002Registry:
    """Load one strict AF-002 preregistration file."""
    payload = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise AF002Error("AF-002 registry must be a mapping")
    folds = payload.get("folds")
    forbidden = payload.get("forbidden_uses")
    if not isinstance(folds, list) or not isinstance(forbidden, list):
        raise AF002Error("AF-002 registry lacks folds or forbidden uses")
    payload["folds"] = tuple(folds)
    payload["forbidden_uses"] = tuple(forbidden)
    return AF002Registry.model_validate(payload)


def evaluate_frames(
    registry: AF002Registry,
    af001: AlphaRegistry,
    af001_result: dict[str, object],
    features: pd.DataFrame,
    labels: pd.DataFrame,
) -> dict[str, object]:
    """Compute fixed folds then deterministic low-redundancy factor candidates."""
    _require_columns(features, ("session", "symbol"))
    _require_columns(labels, ("session", "symbol", LABEL_COLUMN))
    candidates = _af001_candidates(af001_result)
    definitions = {alpha.alpha_id: alpha for alpha in af001.alphas}
    if not candidates or not set(candidates) <= set(definitions):
        raise AF002Error("AF-001 result has no valid frozen candidate set")
    joined = features.merge(labels, on=["session", "symbol"], how="left", validate="one_to_one")
    factor_rows: list[dict[str, object]] = []
    daily_by_factor: dict[str, list[DailyMetric]] = {}
    scores_by_factor: dict[str, pd.DataFrame] = {}
    af001_statuses = _af001_statuses(af001_result)
    for definition in af001.alphas:
        alpha_id = definition.alpha_id
        if alpha_id not in candidates:
            factor_rows.append(
                {
                    "alpha_id": alpha_id,
                    "family": definition.family,
                    "source_feature": definition.source_feature,
                    "score_expression": definition.score_expression,
                    "af001_status": af001_statuses[alpha_id],
                    "folds": [],
                    "stability": {
                        "status": "CARRIED_FORWARD_REJECTED_NO_STABLE_SIGNAL",
                        "positive_fold_fraction": None,
                        "mean_fold_rank_ic": None,
                        "rejection_reasons": ["AF001_REJECTED_NO_STABLE_SIGNAL"],
                    },
                }
            )
            continue
        if definition.source_feature not in joined.columns:
            raise AF002Error(
                f"released view lacks AF-001 source feature: {definition.source_feature}"
            )
        rows = joined.loc[:, ["session", "symbol", LABEL_COLUMN]].copy()
        rows["score"] = definition.multiplier * joined[definition.source_feature].astype(float)
        finite = rows[np.isfinite(rows["score"]) & np.isfinite(rows[LABEL_COLUMN])].copy()
        daily = _daily_metrics(finite, 2)
        daily_by_factor[alpha_id] = daily
        scores_by_factor[alpha_id] = rows.loc[:, ["session", "symbol", "score"]]
        folds = [_fold_metric(registry, fold, rows, daily) for fold in registry.folds]
        stability = _stability(registry.stability, folds)
        factor_rows.append(
            {
                "alpha_id": alpha_id,
                "family": definition.family,
                "source_feature": definition.source_feature,
                "score_expression": definition.score_expression,
                "af001_status": af001_statuses[alpha_id],
                "folds": [asdict(item) for item in folds],
                "stability": stability,
            }
        )
    relations = _relations(candidates, scores_by_factor, daily_by_factor, registry.redundancy)
    clusters = _clusters(factor_rows, relations, registry.redundancy)
    selected = [item["representative_alpha_id"] for item in clusters if item["eligible"]]
    result_status = "AF002_COMPLETED_LIMITED_DEV_DIAGNOSTICS"
    if not selected:
        result_status = "REJECTED_NO_STABLE_SIGNAL"
    return {
        "schema_version": 1,
        "kind": "af002_walk_forward_stability_and_redundancy",
        "status": result_status,
        "label": registry.label,
        "folds": [fold.model_dump(mode="json") for fold in registry.folds],
        "exposure_limitation": {
            "industry": registry.exposure_diagnostics.industry,
            "market_cap": registry.exposure_diagnostics.market_cap,
            "reason": "approved DEV-001 view has Alpha158 features and labels only",
        },
        "factors": sorted(factor_rows, key=lambda item: str(item["alpha_id"])),
        "relations": relations,
        "clusters": clusters,
        "selected_alpha_ids": selected,
        "selected_count": len(selected),
    }


def run_af002(development_root: Path, repo_root: Path, registry_path: Path) -> dict[str, object]:
    """Run AF-002 only against the exact DEV-001 and AF-001 frozen artifacts."""
    registry = load_registry(registry_path)
    summary = _blob(development_root / "dev001" / "summaries", DEV001_SUMMARY_SHA256)
    identities = _mapping(summary, "identities")
    if (
        summary.get("status") != "DEV_REAL_RUN_COMPLETED"
        or summary.get("formal_research") != "BLOCKED_DATA"
        or summary.get("csi500") != "NOT_STARTED"
    ):
        raise AF002Error("DEV-001 summary is outside AF-002 limited scope")
    af001_result = _blob(
        development_root / "af001" / "results", registry.required_af001_result_sha256
    )
    af001_provenance = _mapping(af001_result, "provenance")
    if (
        af001_result.get("status") != "AF001_COMPLETED_LIMITED_DEV_DIAGNOSTICS"
        or af001_result.get("formal_research_status") != "BLOCKED_DATA"
        or af001_result.get("csi500") != "NOT_STARTED"
        or af001_provenance.get("registry_sha256") != registry.required_af001_registry_sha256
        or af001_provenance.get("dev001_summary_sha256") != DEV001_SUMMARY_SHA256
        or af001_provenance.get("contract_sha256") != identities.get("contract_sha256")
        or af001_provenance.get("evidence_sha256") != identities.get("evidence_sha256")
        or af001_provenance.get("view_sha256") != identities.get("view_sha256")
        or af001_provenance.get("validation_target_sha256")
        != identities.get("validation_target_sha256")
    ):
        raise AF002Error("AF-001 result is not a frozen AF-002 input")
    af001_registry = _load_af001_registry(repo_root, registry.required_af001_registry_sha256)
    view = load_staged_view(
        development_root / "dev001" / "authority",
        development_root / "dev001" / "views",
        _string(identities, "contract_sha256"),
        _string(identities, "evidence_sha256"),
        _string(identities, "view_pin_sha256"),
    )
    if (
        view.contract.label_expression != registry.label
        or view.contract.formal_qualification != "BLOCKED_DATA"
        or view.contract.sealed_test != "NOT_STARTED"
        or view.manifest_sha256 != identities.get("view_sha256")
    ):
        raise AF002Error("approved view differs from AF-002 scope")
    train_features = load_features(view, "train")
    validation_features = load_features(view, "validation")
    features = pd.concat([train_features, validation_features], ignore_index=True)
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
    payload = evaluate_frames(registry, af001_registry, af001_result, features, labels)
    payload.update(
        {
            "formal_pit_status": "BLOCKED_DATA",
            "formal_research_status": "BLOCKED_DATA",
            "csi500": "NOT_STARTED",
            "validation_status": "LABEL_PREVIOUSLY_EXPOSED_IN_DEV001_NOT_FRESH_HOLDOUT",
            "provenance": {
                "af002_registry_sha256": sha256(registry_path.read_bytes()).hexdigest(),
                "af001_registry_sha256": registry.required_af001_registry_sha256,
                "af001_result_sha256": registry.required_af001_result_sha256,
                "dev001_summary_sha256": DEV001_SUMMARY_SHA256,
                "contract_sha256": _string(identities, "contract_sha256"),
                "evidence_sha256": _string(identities, "evidence_sha256"),
                "view_sha256": view.manifest_sha256,
                "validation_target_sha256": _string(identities, "validation_target_sha256"),
                "calendar_sha256": view.contract.calendar_sha256,
                "code_sha256": sha256(
                    (repo_root / "src/quant_stack_v2/af002.py").read_bytes()
                ).hexdigest(),
                "git_commit": _git_commit(repo_root),
            },
        }
    )
    return payload


def persist(payload: dict[str, object], result_root: Path) -> str:
    """Write an immutable AF-002 result blob."""
    return write_blob(result_root / "results", canonical(payload))


def render_markdown(payload: dict[str, object], identity: str) -> str:
    """Render AF-002 without portfolio or formal-promotion claims."""
    selected = cast(list[str], payload["selected_alpha_ids"])
    lines = [
        "# AF-002：开发期 Walk-forward 稳定性与因子去冗余",
        "",
        f"状态：`{payload['status']}`；结果 identity：`{identity}`。",
        "仅使用 DEV-001 CSI300 有限开发视图，不含组合收益、回测、模型调参、CSI500 或正式资格结论。",
        "",
        "## 固定结论",
        "",
        f"- 低冗余候选数：{len(selected)}。",
        f"- 候选：{', '.join(selected) if selected else '无；REJECTED_NO_STABLE_SIGNAL'}。",
        "- 行业与市值暴露：`NOT_AVAILABLE_IN_APPROVED_VIEW`；未补取、推断或伪造这些诊断。",
        (
            "- 每个年度 fold 的样本、IC、Rank IC、ICIR、覆盖、缺失和方向，以及全部簇和淘汰理由"
            "均在机器可读结果中。"
        ),
        "",
        (
            "`FORMAL_PIT_STATUS=BLOCKED_DATA`、`FORMAL_RESEARCH_STATUS=BLOCKED_DATA`、"
            "`CSI500=NOT_STARTED` 保持不变。"
        ),
    ]
    return "\n".join(lines) + "\n"


def _fold_metric(
    registry: AF002Registry,
    fold: Fold,
    rows: pd.DataFrame,
    daily: list[DailyMetric],
) -> FoldMetric:
    selected = rows[(rows["session"] >= fold.start) & (rows["session"] <= fold.end)]
    finite = selected[np.isfinite(selected["score"]) & np.isfinite(selected[LABEL_COLUMN])]
    fold_daily = [
        item for item in daily if fold.start <= date.fromisoformat(item.session) <= fold.end
    ]
    return FoldMetric(
        fold_id=fold.fold_id,
        input_rows=len(selected),
        evaluated_rows=len(finite),
        published_view_evaluation_coverage=len(finite) / len(selected) if len(selected) else 0.0,
        within_view_feature_missing_rows=int((~np.isfinite(selected["score"])).sum()),
        label_missing_rows=int((~np.isfinite(selected[LABEL_COLUMN])).sum()),
        metrics=_aggregate(fold_daily),
        industry_exposure=registry.exposure_diagnostics.industry,
        market_cap_exposure=registry.exposure_diagnostics.market_cap,
    )


def _stability(rule: StabilityRule, folds: list[FoldMetric]) -> dict[str, object]:
    valid = [
        fold
        for fold in folds
        if _integer(fold.metrics["defined_days"]) >= rule.minimum_defined_days_per_fold
    ]
    positive = [fold for fold in valid if _positive(fold.metrics["daily_rank_ic"])]
    rank_values = [
        _number(fold.metrics["daily_rank_ic"])
        for fold in valid
        if fold.metrics["daily_rank_ic"] is not None
    ]
    coverage_ok = all(
        fold.published_view_evaluation_coverage >= rule.minimum_evaluation_coverage
        for fold in folds
    )
    fraction = len(positive) / len(folds) if folds else 0.0
    stable = (
        len(valid) == len(folds)
        and coverage_ok
        and fraction >= rule.minimum_positive_fold_fraction
        and bool(rank_values)
        and float(np.mean(rank_values)) > 0
    )
    reasons: list[str] = []
    if len(valid) != len(folds):
        reasons.append("INSUFFICIENT_DEFINED_DAYS")
    if not coverage_ok:
        reasons.append("INSUFFICIENT_EVALUATION_COVERAGE")
    if fraction < rule.minimum_positive_fold_fraction:
        reasons.append("INSUFFICIENT_POSITIVE_FOLDS")
    if not rank_values or float(np.mean(rank_values)) <= 0:
        reasons.append("NON_POSITIVE_MEAN_RANK_IC")
    return {
        "status": "STABLE_CANDIDATE" if stable else "REJECTED_NO_STABLE_SIGNAL",
        "positive_fold_fraction": fraction,
        "mean_fold_rank_ic": float(np.mean(rank_values)) if rank_values else None,
        "rejection_reasons": reasons,
    }


def _relations(
    alpha_ids: list[str],
    scores: dict[str, pd.DataFrame],
    daily: dict[str, list[DailyMetric]],
    rule: RedundancyRule,
) -> list[dict[str, object]]:
    result: list[dict[str, object]] = []
    for left_index, left in enumerate(alpha_ids):
        for right in alpha_ids[left_index + 1 :]:
            merged = scores[left].merge(
                scores[right], on=["session", "symbol"], suffixes=("_left", "_right")
            )
            value = _mean_daily_value_correlation(merged)
            ic = _daily_series_correlation(daily[left], daily[right], "ic")
            rank_ic = _daily_series_correlation(daily[left], daily[right], "rank_ic")
            overlap = _top_score_overlap(merged, rule.top_score_fraction)
            undefined = value is None or ic is None or rank_ic is None
            related = (
                _above(value, rule.absolute_value_correlation_threshold)
                or _above(ic, rule.absolute_ic_correlation_threshold)
                or _above(rank_ic, rule.absolute_ic_correlation_threshold)
                or overlap >= rule.top_score_proxy_overlap_threshold
                or (undefined and rule.undefined_relation_is_redundant)
            )
            result.append(
                {
                    "left_alpha_id": left,
                    "right_alpha_id": right,
                    "mean_daily_value_correlation": value,
                    "daily_ic_correlation": ic,
                    "daily_rank_ic_correlation": rank_ic,
                    "top_score_proxy_overlap": overlap,
                    "undefined_relation": undefined,
                    "redundant": related,
                }
            )
    return result


def _clusters(
    factors: list[dict[str, object]], relations: list[dict[str, object]], rule: RedundancyRule
) -> list[dict[str, object]]:
    stable = {
        str(item["alpha_id"]): item
        for item in factors
        if _mapping(item, "stability")["status"] == "STABLE_CANDIDATE"
    }
    adjacency: dict[str, set[str]] = {alpha: set() for alpha in stable}
    for relation in relations:
        left, right = str(relation["left_alpha_id"]), str(relation["right_alpha_id"])
        if relation["redundant"] and left in adjacency and right in adjacency:
            adjacency[left].add(right)
            adjacency[right].add(left)
    groups: list[list[str]] = []
    unseen = set(stable)
    while unseen:
        seed = min(unseen)
        queue, group = [seed], []
        unseen.remove(seed)
        while queue:
            current = queue.pop()
            group.append(current)
            for neighbor in sorted(adjacency[current] & unseen):
                unseen.remove(neighbor)
                queue.append(neighbor)
        groups.append(sorted(group))
    representatives = [
        (
            sorted(
                group,
                key=lambda alpha: (
                    -_number(_mapping(stable[alpha], "stability")["mean_fold_rank_ic"]),
                    alpha,
                ),
            )[0],
            group,
        )
        for group in groups
    ]
    ranked = sorted(
        representatives,
        key=lambda item: (
            -_number(_mapping(stable[item[0]], "stability")["mean_fold_rank_ic"]),
            item[0],
        ),
    )
    output: list[dict[str, object]] = []
    for position, (representative, group) in enumerate(ranked):
        eligible = position < rule.maximum_candidates
        output.append(
            {
                "cluster_alpha_ids": group,
                "representative_alpha_id": representative,
                "eligible": eligible,
                "discarded_alpha_ids": [alpha for alpha in group if alpha != representative],
                "discard_reason": "REDUNDANT_CLUSTER_REPRESENTATIVE" if len(group) > 1 else None,
            }
        )
    return output


def _mean_daily_value_correlation(frame: pd.DataFrame) -> float | None:
    values: list[float] = []
    for _, group in frame.groupby("session", sort=True):
        left = group["score_left"].to_numpy(dtype=float)
        right = group["score_right"].to_numpy(dtype=float)
        if (
            len(group) >= 2
            and np.isfinite(left).all()
            and np.isfinite(right).all()
            and np.var(left)
            and np.var(right)
        ):
            values.append(float(np.corrcoef(left, right)[0, 1]))
    return float(np.mean(values)) if values else None


def _daily_series_correlation(
    left: list[DailyMetric], right: list[DailyMetric], field: Literal["ic", "rank_ic"]
) -> float | None:
    left_values = {item.session: getattr(item, field) for item in left}
    right_values = {item.session: getattr(item, field) for item in right}
    aligned = sorted(left_values.keys() & right_values.keys())
    first = np.asarray([left_values[session] for session in aligned])
    second = np.asarray([right_values[session] for session in aligned])
    if len(first) < 2 or np.var(first) == 0 or np.var(second) == 0:
        return None
    return float(np.corrcoef(first, second)[0, 1])


def _top_score_overlap(frame: pd.DataFrame, fraction: float) -> float:
    values: list[float] = []
    for _, group in frame.groupby("session", sort=True):
        count = max(1, math.ceil(len(group) * fraction))
        left = set(group.nlargest(count, "score_left", keep="all")["symbol"])
        right = set(group.nlargest(count, "score_right", keep="all")["symbol"])
        values.append(len(left & right) / len(left | right))
    return float(np.mean(values)) if values else 0.0


def _af001_candidates(result: dict[str, object]) -> list[str]:
    rows = result.get("alphas")
    if not isinstance(rows, list):
        raise AF002Error("AF-001 result has invalid alpha rows")
    return [
        str(row["alpha_id"])
        for row in rows
        if isinstance(row, dict) and row.get("status") == "CANDIDATE_PENDING_AF002"
    ]


def _af001_statuses(result: dict[str, object]) -> dict[str, str]:
    rows = result.get("alphas")
    if not isinstance(rows, list):
        raise AF002Error("AF-001 result has invalid alpha rows")
    statuses = {
        str(row["alpha_id"]): str(row["status"])
        for row in rows
        if isinstance(row, dict)
        and isinstance(row.get("alpha_id"), str)
        and isinstance(row.get("status"), str)
    }
    if len(statuses) != len(rows):
        raise AF002Error("AF-001 result has malformed alpha status")
    return statuses


def _load_af001_registry(repo_root: Path, expected: str) -> AlphaRegistry:
    path = repo_root / "configs/v2/alphas/af_001_alpha_registry_v1.yaml"
    if sha256(path.read_bytes()).hexdigest() != expected:
        raise AF002Error("tracked AF-001 registry hash differs from frozen input")
    from quant_stack_v2.af001 import load_registry as load_af001_registry

    return load_af001_registry(path)


def _blob(root: Path, identity: str) -> dict[str, object]:
    value = json.loads(read_blob(root, identity))
    if not isinstance(value, dict):
        raise AF002Error("frozen result must be a mapping")
    return cast(dict[str, object], value)


def _mapping(value: dict[str, object], key: str) -> dict[str, object]:
    item = value.get(key)
    if not isinstance(item, dict):
        raise AF002Error(f"expected mapping: {key}")
    return cast(dict[str, object], item)


def _string(value: dict[str, object], key: str) -> str:
    item = value.get(key)
    if not isinstance(item, str):
        raise AF002Error(f"expected string: {key}")
    return item


def _require_columns(frame: pd.DataFrame, names: tuple[str, ...]) -> None:
    if not set(names) <= set(frame.columns):
        raise AF002Error("AF-002 frame schema is incomplete")


def _positive(value: object) -> bool:
    return value is not None and _number(value) > 0


def _above(value: float | None, threshold: float) -> bool:
    return value is not None and abs(value) >= threshold


def _number(value: object) -> float:
    if isinstance(value, bool) or not isinstance(value, (float, int)):
        raise AF002Error("expected numeric diagnostic")
    return float(value)


def _integer(value: object) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise AF002Error("expected integer diagnostic")
    return value


def _git_commit(repo_root: Path) -> str:
    return subprocess.run(
        ["git", "-C", str(repo_root), "rev-parse", "HEAD"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()


def main() -> None:
    """Execute AF-002 only from the restricted development-result root."""
    parser = argparse.ArgumentParser()
    parser.add_argument("--development-root", type=Path, required=True)
    parser.add_argument("--repo-root", type=Path, required=True)
    parser.add_argument("--registry", type=Path, required=True)
    parser.add_argument("--result-root", type=Path, required=True)
    parser.add_argument("--report", type=Path, required=True)
    args = parser.parse_args()
    payload = run_af002(args.development_root, args.repo_root, args.registry)
    identity = persist(payload, args.result_root)
    args.report.write_text(render_markdown(payload, identity), encoding="utf-8")
    print(json.dumps({"status": payload["status"], "result_sha256": identity}, sort_keys=True))


if __name__ == "__main__":
    main()
