# ruff: noqa: RUF001
"""AF-001 preregistered Alpha158 single-factor diagnostics."""

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

from quant_stack_v2.dev_contract import Digest, StrictModel, canonical, read_blob, write_blob
from quant_stack_v2.dev_real_staged_view import (
    LABEL_COLUMN,
    VerifiedStagedView,
    load_features,
    load_staged_view,
    load_validation_labels,
)

DEV001_SUMMARY_SHA256 = "606b072c361fd73f0da29d4ae4070dac31cf2e2a11f184be09fe929b06b13472"


class AF001Error(ValueError):
    """Raised when an AF-001 input violates its frozen development scope."""


class EvaluationRule(StrictModel):
    """Fixed single-factor diagnostic and non-promotion decision rules."""

    split: Literal["validation"]
    minimum_cross_section: int = Field(ge=2)
    minimum_defined_days: int = Field(ge=1)
    minimum_evaluation_coverage: float = Field(ge=0.0, le=1.0)
    minimum_direction_consistency: float = Field(ge=0.0, le=1.0)
    segments: tuple[Literal["calendar_year", "contract_quarters"], ...]


class AlphaDefinition(StrictModel):
    """One immutable factor assembled from exactly one released Alpha158 field."""

    alpha_id: str = Field(pattern=r"^CN_[A-Z]+_[0-9]{3}$")
    family: Literal["momentum", "reversal", "volatility", "price_volume", "range_position"]
    hypothesis: str = Field(min_length=1)
    source_feature: str = Field(pattern=r"^[A-Z][A-Z0-9]*$")
    source_expression: str = Field(min_length=1)
    score_expression: str = Field(min_length=1)
    multiplier: Literal[-1, 1]
    expected_sign: Literal["positive"]
    lookback_sessions: int = Field(ge=1, le=60)
    required_fields: tuple[str, ...]
    known_risks: tuple[str, ...]

    @model_validator(mode="after")
    def direct_alpha158_transform(self) -> AlphaDefinition:
        if self.required_fields != (self.source_feature,):
            raise ValueError("AF-001 alpha must depend on exactly its source feature")
        expected = self.source_feature if self.multiplier == 1 else f"-{self.source_feature}"
        if self.score_expression != expected:
            raise ValueError("AF-001 score expression differs from direct frozen transform")
        return self


class AlphaRegistry(StrictModel):
    """Versioned AF-001 registry bound to the DEV-001 feature identity."""

    schema_version: Literal[1]
    registry_id: Literal["AF-001-CSI300-ALPHA158-V1"]
    status: Literal["PREREGISTERED"]
    scope: Literal["LIMITED_DEV_RESEARCH"]
    run_id: Literal["DEV-001"]
    universe: Literal["csi300"]
    required_use_config_sha256: Digest
    required_alpha158_expression_sha256: Digest
    label: Literal["close[T+2] / close[T+1] - 1"]
    evaluation: EvaluationRule
    alphas: tuple[AlphaDefinition, ...]

    @model_validator(mode="after")
    def complete_preregistration(self) -> AlphaRegistry:
        if not 12 <= len(self.alphas) <= 20:
            raise ValueError("AF-001 requires 12 to 20 preregistered alphas")
        if len({alpha.alpha_id for alpha in self.alphas}) != len(self.alphas):
            raise ValueError("AF-001 alpha identifiers must be unique")
        if self.evaluation.segments != ("calendar_year", "contract_quarters"):
            raise ValueError("AF-001 requires fixed annual and contract-quarter diagnostics")
        return self


@dataclass(frozen=True)
class DailyMetric:
    """One eligible daily cross-sectional diagnostic."""

    session: str
    ic: float
    rank_ic: float
    rows: int


def load_registry(path: Path) -> AlphaRegistry:
    """Load one strict, versioned AF-001 preregistration file."""
    payload = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise AF001Error("AF-001 registry must be a mapping")
    evaluation = payload.get("evaluation")
    alphas = payload.get("alphas")
    if not isinstance(evaluation, dict) or not isinstance(alphas, list):
        raise AF001Error("AF-001 registry lacks evaluation or alpha rows")
    evaluation["segments"] = tuple(evaluation.get("segments", ()))
    for alpha in alphas:
        if not isinstance(alpha, dict):
            raise AF001Error("AF-001 alpha row must be a mapping")
        alpha["required_fields"] = tuple(alpha.get("required_fields", ()))
        alpha["known_risks"] = tuple(alpha.get("known_risks", ()))
    payload["alphas"] = tuple(alphas)
    return AlphaRegistry.model_validate(payload)


def evaluate_frames(
    registry: AlphaRegistry,
    features: pd.DataFrame,
    labels: pd.DataFrame,
    *,
    member_signal_rows: int,
    feature_cells: int,
    missing_feature_cells: int,
    segments: dict[str, tuple[date, date]],
) -> dict[str, object]:
    """Evaluate every preregistered factor on the fixed validation-label release."""
    _require_columns(features, ("session", "symbol"))
    _require_columns(labels, ("session", "symbol", LABEL_COLUMN))
    if member_signal_rows < len(features) or feature_cells < missing_feature_cells:
        raise AF001Error("staged-view coverage counts are invalid")
    joined = features.merge(labels, on=["session", "symbol"], how="left", validate="one_to_one")
    result: list[dict[str, object]] = []
    for alpha in registry.alphas:
        if alpha.source_feature not in joined.columns:
            raise AF001Error(f"released view lacks preregistered feature: {alpha.source_feature}")
        score = alpha.multiplier * joined[alpha.source_feature].astype(float)
        rows = joined.loc[:, ["session", "symbol", LABEL_COLUMN]].copy()
        rows["score"] = score
        eligible = rows[np.isfinite(rows["score"]) & np.isfinite(rows[LABEL_COLUMN])].copy()
        daily = _daily_metrics(eligible, registry.evaluation.minimum_cross_section)
        metrics = _aggregate(daily)
        coverage = len(eligible) / member_signal_rows if member_signal_rows else 0.0
        source_missing = int((~np.isfinite(rows["score"])).sum())
        label_missing = int((~np.isfinite(rows[LABEL_COLUMN])).sum())
        segment_metrics = {
            name: _aggregate(
                [item for item in daily if start <= date.fromisoformat(item.session) <= end]
            )
            for name, (start, end) in segments.items()
        }
        status = _status(metrics, coverage, registry.evaluation)
        result.append(
            {
                "alpha_id": alpha.alpha_id,
                "family": alpha.family,
                "status": status,
                "source_feature": alpha.source_feature,
                "score_expression": alpha.score_expression,
                "expected_sign": alpha.expected_sign,
                "lookback_sessions": alpha.lookback_sessions,
                "input_rows": len(rows),
                "evaluated_rows": len(eligible),
                "evaluation_coverage": coverage,
                "within_view_source_missing_rows": source_missing,
                "within_view_label_missing_rows": label_missing,
                "daily": [asdict(item) for item in daily],
                "metrics": metrics,
                "segments": segment_metrics,
            }
        )
    return {
        "schema_version": 1,
        "kind": "af001_single_factor_diagnostics",
        "registry_id": registry.registry_id,
        "label": registry.label,
        "evaluation_rule": registry.evaluation.model_dump(mode="json"),
        "coverage": {
            "member_signal_rows": member_signal_rows,
            "complete_feature_rows": len(features),
            "member_grid_feature_coverage": len(features) / member_signal_rows
            if member_signal_rows
            else 0.0,
            "aggregate_feature_cell_missing_rate": missing_feature_cells / feature_cells
            if feature_cells
            else None,
            "within_view_feature_missing_rate": 0.0,
            "limitation": (
                "released view contains only complete Alpha158 rows; "
                "factor-level prefilter missingness is not reconstructable"
            ),
        },
        "alphas": result,
    }


def run_af001(development_root: Path, repo_root: Path, registry_path: Path) -> dict[str, object]:
    """Bind AF-001 to the completed DEV-001 development view and target release."""
    registry = load_registry(registry_path)
    summary = _json_blob(development_root / "summaries", DEV001_SUMMARY_SHA256)
    identities = _mapping(summary, "identities")
    if (
        summary.get("status") != "DEV_REAL_RUN_COMPLETED"
        or summary.get("formal_research") != "BLOCKED_DATA"
        or summary.get("csi500") != "NOT_STARTED"
        or identities.get("use_config_sha256") != registry.required_use_config_sha256
        or identities.get("alpha158_expression_sha256")
        != registry.required_alpha158_expression_sha256
    ):
        raise AF001Error("DEV-001 summary is not an approved AF-001 input")
    contract_sha = _string(identities, "contract_sha256")
    evidence_sha = _string(identities, "evidence_sha256")
    view_pin_sha = _string(identities, "view_pin_sha256")
    target_sha = _string(identities, "validation_target_sha256")
    view = load_staged_view(
        development_root / "authority",
        development_root / "views",
        contract_sha,
        evidence_sha,
        view_pin_sha,
    )
    _verify_view(view, registry, identities)
    features = load_features(view, "validation")
    labels = load_validation_labels(view, development_root / "views", target_sha)
    payload = evaluate_frames(
        registry,
        features,
        labels,
        member_signal_rows=view.manifest.exclusions["validation"].member_signal_rows,
        feature_cells=view.manifest.exclusions["validation"].feature_cells,
        missing_feature_cells=view.manifest.exclusions["validation"].missing_feature_cells,
        segments=_segments(view),
    )
    registry_sha = sha256(registry_path.read_bytes()).hexdigest()
    code_sha = sha256((repo_root / "src/quant_stack_v2/af001.py").read_bytes()).hexdigest()
    payload.update(
        {
            "status": "AF001_COMPLETED_LIMITED_DEV_DIAGNOSTICS",
            "formal_pit_status": "BLOCKED_DATA",
            "formal_research_status": "BLOCKED_DATA",
            "csi500": "NOT_STARTED",
            "validation_status": "LABEL_PREVIOUSLY_EXPOSED_IN_DEV001_NOT_FRESH_HOLDOUT",
            "provenance": {
                "dev001_summary_sha256": DEV001_SUMMARY_SHA256,
                "registry_sha256": registry_sha,
                "code_sha256": code_sha,
                "git_commit": _git_commit(repo_root),
                "contract_sha256": contract_sha,
                "evidence_sha256": evidence_sha,
                "view_sha256": view.manifest_sha256,
                "validation_target_sha256": target_sha,
                "calendar_sha256": view.contract.calendar_sha256,
            },
        }
    )
    return payload


def persist(payload: dict[str, object], result_root: Path) -> str:
    """Write a content-addressed AF-001 result without overwriting prior runs."""
    return write_blob(result_root / "results", canonical(payload))


def render_markdown(payload: dict[str, object], result_sha256: str) -> str:
    """Render a concise AF-001 result report without portfolio claims."""
    coverage = _mapping(payload, "coverage")
    rows = cast(list[dict[str, object]], payload["alphas"])
    lines = [
        "# AF-001：CSI300 Alpha158 可解释单因子筛选",
        "",
        "状态：`AF001_COMPLETED_LIMITED_DEV_DIAGNOSTICS`。仅为有限开发期信号诊断；不包含组合收益、CAGR、Sharpe、交易、晋级或正式资格结论。",
        "",
        f"结果 identity：`{result_sha256}`。",
        f"注册表：`{_mapping(payload, 'provenance')['registry_sha256']}`。",
        "",
        "## 覆盖与限制",
        "",
        f"- member-at-T 行：{coverage['member_signal_rows']}。",
        f"- 完整特征行：{coverage['complete_feature_rows']}。",
        f"- 成员网格覆盖：{_number(coverage['member_grid_feature_coverage']):.6%}。",
        "- 已发布视图内特征缺失率：0；导出前 aggregate feature-cell 缺失率："
        f"{_fmt(coverage['aggregate_feature_cell_missing_rate'])}。",
        f"- {coverage['limitation']}。",
        "",
        "## 固定评价结果",
        "",
        (
            "| Alpha | Family | Status | Rows | Coverage | IC | Rank IC | ICIR | "
            "Rank ICIR | Direction | Days |"
        ),
        "| --- | --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    for item in rows:
        metrics = _mapping(item, "metrics")
        lines.append(
            f"| {item['alpha_id']} | {item['family']} | {item['status']} | "
            f"{item['evaluated_rows']} | {_number(item['evaluation_coverage']):.6%} | "
            f"{_fmt(metrics['daily_ic'])} | "
            f"{_fmt(metrics['daily_rank_ic'])} | {_fmt(metrics['icir'])} | "
            f"{_fmt(metrics['rank_icir'])} | {_fmt(metrics['rank_direction_consistency'])} | "
            f"{metrics['defined_days']} |"
        )
    lines += [
        "",
        "季度和年度固定分段、逐日 IC/Rank IC、缺失行计数及完整 provenance 均在机器可读结果中。",
        "`FORMAL_PIT_STATUS=BLOCKED_DATA`、`FORMAL_RESEARCH_STATUS=BLOCKED_DATA`、",
        "`CSI500=NOT_STARTED` 保持不变。",
        "验证标签在 DEV-001 已开放，不能表述为新鲜 holdout。任何",
        "`CANDIDATE_PENDING_AF002` 仅表示满足预注册诊断规则，仍需 AF-002 复核。",
        "",
    ]
    return "\n".join(lines)


def _daily_metrics(frame: pd.DataFrame, minimum_cross_section: int) -> list[DailyMetric]:
    result: list[DailyMetric] = []
    for session, group in frame.groupby("session", sort=True):
        score = group["score"].to_numpy(dtype=float)
        label = group[LABEL_COLUMN].to_numpy(dtype=float)
        if len(group) < minimum_cross_section or np.var(score) == 0 or np.var(label) == 0:
            continue
        ic = float(np.corrcoef(score, label)[0, 1])
        rank_ic = float(
            np.corrcoef(
                pd.Series(score).rank(method="average").to_numpy(),
                pd.Series(label).rank(method="average").to_numpy(),
            )[0, 1]
        )
        if math.isfinite(ic) and math.isfinite(rank_ic):
            result.append(DailyMetric(cast(date, session).isoformat(), ic, rank_ic, len(group)))
    return result


def _aggregate(daily: list[DailyMetric]) -> dict[str, object]:
    if not daily:
        return {
            "daily_ic": None,
            "daily_rank_ic": None,
            "icir": None,
            "rank_icir": None,
            "rank_direction_consistency": None,
            "defined_days": 0,
            "undefined_reason": "INSUFFICIENT_OR_CONSTANT_DAILY_CROSS_SECTIONS",
        }
    ic = np.asarray([item.ic for item in daily], dtype=float)
    rank = np.asarray([item.rank_ic for item in daily], dtype=float)
    return {
        "daily_ic": float(np.mean(ic)),
        "daily_rank_ic": float(np.mean(rank)),
        "icir": _ratio(ic),
        "rank_icir": _ratio(rank),
        "rank_direction_consistency": float(np.mean(rank > 0)),
        "defined_days": len(daily),
        "undefined_reason": None,
    }


def _ratio(values: np.ndarray) -> float | None:
    if len(values) < 2:
        return None
    deviation = float(np.std(values, ddof=1))
    return float(np.mean(values) / deviation) if deviation > 0 else None


def _status(metrics: dict[str, object], coverage: float, rule: EvaluationRule) -> str:
    rank_ic = metrics["daily_rank_ic"]
    direction = metrics["rank_direction_consistency"]
    if rank_ic is None or direction is None:
        return "REGISTERED"
    if (
        _integer(metrics["defined_days"]) >= rule.minimum_defined_days
        and coverage >= rule.minimum_evaluation_coverage
        and _number(rank_ic) > 0
        and _number(direction) >= rule.minimum_direction_consistency
    ):
        return "CANDIDATE_PENDING_AF002"
    return "REJECTED_NO_STABLE_SIGNAL"


def _verify_view(
    view: VerifiedStagedView, registry: AlphaRegistry, identities: dict[str, object]
) -> None:
    if (
        view.contract.run_id != registry.run_id
        or view.contract.universe != registry.universe
        or view.contract.formal_qualification != "BLOCKED_DATA"
        or view.contract.sealed_test != "NOT_STARTED"
        or view.contract.alpha158.expression_sha256 != registry.required_alpha158_expression_sha256
        or view.manifest_sha256 != identities.get("view_sha256")
        or view.contract.label_expression != registry.label
    ):
        raise AF001Error("released view differs from AF-001 preregistration")
    expressions = dict(
        zip(view.contract.alpha158.names, view.contract.alpha158.expressions, strict=True)
    )
    for alpha in registry.alphas:
        if expressions.get(alpha.source_feature) != alpha.source_expression:
            raise AF001Error(f"Alpha158 formula changed for {alpha.alpha_id}")


def _segments(view: VerifiedStagedView) -> dict[str, tuple[date, date]]:
    result: dict[str, tuple[date, date]] = {}
    for span in view.contract.diagnostic_segments:
        result[f"quarter_{span.start.isoformat()}_{span.end.isoformat()}"] = (span.start, span.end)
    result["year_2020"] = (view.contract.validation.start, view.contract.validation.end)
    return result


def _json_blob(root: Path, identity: str) -> dict[str, object]:
    payload = json.loads(read_blob(root, identity))
    if not isinstance(payload, dict):
        raise AF001Error("content-addressed DEV-001 summary must be an object")
    return cast(dict[str, object], payload)


def _mapping(payload: dict[str, object], key: str) -> dict[str, object]:
    value = payload.get(key)
    if not isinstance(value, dict):
        raise AF001Error(f"expected object: {key}")
    return cast(dict[str, object], value)


def _string(payload: dict[str, object], key: str) -> str:
    value = payload.get(key)
    if not isinstance(value, str):
        raise AF001Error(f"expected string: {key}")
    return value


def _require_columns(frame: pd.DataFrame, names: tuple[str, ...]) -> None:
    missing = set(names) - set(frame.columns)
    if missing:
        raise AF001Error(f"frame misses required columns: {sorted(missing)}")


def _git_commit(repo_root: Path) -> str:
    return subprocess.run(
        ["git", "-C", str(repo_root), "rev-parse", "HEAD"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()


def _fmt(value: object) -> str:
    return "undefined" if value is None else f"{_number(value):.8f}"


def _number(value: object) -> float:
    if type(value) not in (int, float):
        raise AF001Error("expected finite numeric result")
    converted = float(cast(float, value))
    if not math.isfinite(converted):
        raise AF001Error("expected finite numeric result")
    return converted


def _integer(value: object) -> int:
    if type(value) is not int:
        raise AF001Error("expected integer result")
    return value


def main() -> None:
    """Run AF-001 only through the existing limited development root."""
    parser = argparse.ArgumentParser()
    parser.add_argument("--development-root", type=Path, required=True)
    parser.add_argument("--repo-root", type=Path, required=True)
    parser.add_argument("--registry", type=Path, required=True)
    parser.add_argument("--result-root", type=Path, required=True)
    parser.add_argument("--report", type=Path, required=True)
    args = parser.parse_args()
    payload = run_af001(args.development_root, args.repo_root, args.registry)
    identity = persist(payload, args.result_root)
    args.report.write_text(render_markdown(payload, identity), encoding="utf-8")
    print(
        json.dumps(
            {
                "result_sha256": identity,
                "status": payload["status"],
                "formal_pit_status": payload["formal_pit_status"],
                "formal_research_status": payload["formal_research_status"],
                "csi500": payload["csi500"],
                "report": str(args.report),
            },
            ensure_ascii=False,
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
