# ruff: noqa: E501, RUF001
"""EXQ-001 candidate-scope qualification without exporting sealed market data."""

from __future__ import annotations

import argparse
import json
import re
import stat
import subprocess
from datetime import date
from hashlib import sha256
from pathlib import Path
from typing import Any, Literal, cast

import yaml

from quant_stack_v2.af001 import load_registry as load_af001_registry
from quant_stack_v2.af002 import _blob, _mapping, _string
from quant_stack_v2.af003 import DEV001_SUMMARY_SHA256
from quant_stack_v2.dev001 import ARCHIVE_SHA256, CORRECTION_RELATIVE, TREE_SHA256, _members
from quant_stack_v2.dev_contract import Digest, StrictModel, canonical, write_blob
from quant_stack_v2.dev_real_staged_view import (
    corrected_members,
    load_staged_view,
    membership_identity,
)


class EXQ001Error(ValueError):
    """Raised when a frozen EXQ-001 input or scope binding is invalid."""


class Registry(StrictModel):
    """Frozen candidate and free-evidence identities for EXQ-001."""

    schema_version: Literal[1]
    registry_id: Literal["EXQ-001-CSI300-CANDIDATE-SCOPE-V1"]
    status: Literal["PREREGISTERED"]
    scope: Literal["LIMITED_DEV_RESEARCH"]
    run_id: Literal["DEV-001"]
    universe: Literal["csi300"]
    required_af003_result_sha256: Digest
    required_simple_model: Literal["equal_weight_zscore"]
    required_ml_challenger: Literal["NO_STABLE_ML_INCREMENT"]
    required_free_residual_sha256: Digest
    required_free_intervals_sha256: Digest
    required_free_funnel_sha256: Digest
    required_free_initial_missing: Literal[15743]
    required_free_unexplained: Literal[540]
    required_free_conflicts: Literal[0]
    required_candidate_alpha_ids: tuple[str, ...]
    required_execution_semantics: tuple[
        Literal["t_plus_one", "price_limit", "board_lot", "liquidity", "costs"], ...
    ]
    forbidden_uses: tuple[str, ...]


def load_registry(path: Path) -> Registry:
    """Load the strict, versioned EXQ-001 scope registry."""
    value = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise EXQ001Error("EXQ-001 registry must be a mapping")
    for key in ("required_candidate_alpha_ids", "required_execution_semantics", "forbidden_uses"):
        if not isinstance(value.get(key), list):
            raise EXQ001Error(f"EXQ-001 registry lacks list: {key}")
        value[key] = tuple(value[key])
    registry = Registry.model_validate(value)
    if registry.forbidden_uses != (
        "csi500",
        "sealed_test",
        "portfolio_returns",
        "parameter_search",
        "promotion",
        "live_order",
        "network",
    ):
        raise EXQ001Error("EXQ-001 forbidden-use boundary changed")
    return registry


def _frozen_json(path: Path, identity: str) -> dict[str, Any]:
    """Open one fixed archive object and verify its hash without following links."""
    info = path.lstat()
    if not stat.S_ISREG(info.st_mode) or stat.S_ISLNK(info.st_mode):
        raise EXQ001Error("frozen evidence must be a regular non-symlink file")
    body = path.read_bytes()
    if sha256(body).hexdigest() != identity:
        raise EXQ001Error("frozen evidence SHA-256 mismatch")
    value = json.loads(body)
    if not isinstance(value, dict):
        raise EXQ001Error("frozen evidence must be an object")
    return value


def _candidate_dependencies(
    repo_root: Path, candidates: tuple[str, ...]
) -> dict[str, tuple[str, ...]]:
    """Resolve direct Alpha158 raw-field dependencies without reading market values."""
    registry = load_af001_registry(repo_root / "configs/v2/alphas/af_001_alpha_registry_v1.yaml")
    definitions = {item.alpha_id: item for item in registry.alphas}
    if not set(candidates) <= set(definitions):
        raise EXQ001Error("candidate alpha absent from AF-001 registry")
    output: dict[str, tuple[str, ...]] = {}
    for alpha in candidates:
        fields = tuple(sorted(set(re.findall(r"\$([a-z]+)", definitions[alpha].source_expression))))
        if not fields:
            raise EXQ001Error("candidate expression has no raw dependency")
        output[alpha] = fields
    return output


def _residual_intersection(
    residual: dict[str, Any],
    members: tuple[Any, ...],
    sessions: tuple[date, ...],
    signal_spans: tuple[Any, ...],
    lookbacks: dict[str, int],
) -> list[dict[str, object]]:
    """Expand candidate field/label dependencies and intersect exact frozen keys."""
    rows = residual.get("residual")
    if not isinstance(rows, list):
        raise EXQ001Error("free residual schema lacks rows")
    positions = {day: position for position, day in enumerate(sessions)}
    signal_days = {
        day for day in sessions if any(span.start <= day <= span.end for span in signal_spans)
    }
    by_symbol: dict[str, tuple[Any, ...]] = {}
    for member in members:
        by_symbol.setdefault(member.symbol, ())
        by_symbol[member.symbol] += (member,)
    selected: list[dict[str, object]] = []
    for row in rows:
        if not isinstance(row, dict) or row.get("classification") not in {
            "UNEXPLAINED",
            "PROVIDER_CONFLICT",
        }:
            raise EXQ001Error("free residual contains a nonblocking row")
        symbol, session = row.get("symbol"), row.get("session")
        if not isinstance(symbol, str) or not isinstance(session, str):
            raise EXQ001Error("free residual key is invalid")
        day = date.fromisoformat(session)
        if day not in positions:
            continue
        impacts: list[dict[str, object]] = []
        for alpha, lookback in lookbacks.items():
            for offset in range(lookback + 1):
                signal_position = positions[day] + offset
                if signal_position >= len(sessions):
                    break
                signal_day = sessions[signal_position]
                if signal_day not in signal_days or not _is_member(
                    by_symbol.get(symbol, ()), signal_day
                ):
                    continue
                impacts.append(
                    {
                        "alpha_id": alpha,
                        "signal_session": signal_day.isoformat(),
                        "dependency_role": "FEATURE_LOOKBACK",
                    }
                )
        for offset, role in ((1, "LABEL_T_PLUS_1"), (2, "LABEL_T_PLUS_2")):
            signal_position = positions[day] - offset
            if signal_position < 0:
                continue
            signal_day = sessions[signal_position]
            if signal_day in signal_days and _is_member(by_symbol.get(symbol, ()), signal_day):
                impacts.append(
                    {
                        "alpha_id": "ALL_CANDIDATES",
                        "signal_session": signal_day.isoformat(),
                        "dependency_role": role,
                    }
                )
        if impacts:
            selected.append(
                {
                    "symbol": symbol,
                    "expected_session": session,
                    "classification": str(row["classification"]),
                    "impacts": impacts,
                }
            )
    return sorted(selected, key=lambda row: (str(row["symbol"]), str(row["expected_session"])))


def _is_member(members: tuple[Any, ...], day: date) -> bool:
    """Return membership at the signal date without using future membership state."""
    return any(member.start <= day <= member.end for member in members)


def qualify(
    development_root: Path, sealed_root: Path, repo_root: Path, registry_path: Path
) -> dict[str, object]:
    """Audit only AF-003's frozen candidate scope and return a fail-closed result."""
    registry = load_registry(registry_path)
    summary = _blob(development_root / "dev001" / "summaries", DEV001_SUMMARY_SHA256)
    identities = _mapping(summary, "identities")
    af003 = _blob(development_root / "af003" / "results", registry.required_af003_result_sha256)
    if (
        summary.get("status") != "DEV_REAL_RUN_COMPLETED"
        or summary.get("formal_research") != "BLOCKED_DATA"
        or summary.get("csi500") != "NOT_STARTED"
        or af003.get("status") != "AF003_COMPLETED_LIMITED_DEV_DIAGNOSTICS"
        or af003.get("selected_simple_model") != registry.required_simple_model
        or af003.get("selected_ml_challenger") != registry.required_ml_challenger
        or af003.get("formal_research_status") != "BLOCKED_DATA"
        or af003.get("csi500") != "NOT_STARTED"
    ):
        raise EXQ001Error("DEV-001 or AF-003 is outside frozen EXQ-001 scope")
    if _mapping(af003, "provenance").get("dev001_summary_sha256") != DEV001_SUMMARY_SHA256:
        raise EXQ001Error("AF-003 is not bound to DEV-001")
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
        or view.contract.universe != registry.universe
        or view.manifest_sha256 != identities.get("view_sha256")
    ):
        raise EXQ001Error("staged view does not match EXQ-001 scope")
    dependencies = _candidate_dependencies(repo_root, registry.required_candidate_alpha_ids)
    required_raw_fields = tuple(
        sorted({field for fields in dependencies.values() for field in fields})
    )
    if not set(required_raw_fields) <= set(view.contract.alpha158.raw_dependencies):
        raise EXQ001Error("candidate raw dependency is outside Alpha158 contract")
    free_root = sealed_root / "artifacts/v2/free_evidence_funnel"
    residual = _frozen_json(
        free_root / "residual" / f"{registry.required_free_residual_sha256}.json",
        registry.required_free_residual_sha256,
    )
    intervals = _frozen_json(
        free_root / "intervals" / f"{registry.required_free_intervals_sha256}.json",
        registry.required_free_intervals_sha256,
    )
    funnel = _frozen_json(
        free_root / "funnel" / f"{registry.required_free_funnel_sha256}.json",
        registry.required_free_funnel_sha256,
    )
    counts = _mapping(funnel, "final_class_counts")
    if (
        funnel.get("initial_missing") != registry.required_free_initial_missing
        or counts.get("UNEXPLAINED") != registry.required_free_unexplained
        or counts.get("PROVIDER_CONFLICT") != registry.required_free_conflicts
        or funnel.get("FORMAL_PIT_STATUS") != "BLOCKED_DATA"
        or funnel.get("FORMAL_RESEARCH_STATUS") != "BLOCKED_DATA"
    ):
        raise EXQ001Error("free-evidence funnel identity or status differs from registry")
    member_file = (
        sealed_root
        / "artifacts/v2/qlib_import"
        / ARCHIVE_SHA256
        / "trees"
        / TREE_SHA256
        / "qlib_bin/instruments/csi300.txt"
    )
    correction = _frozen_json(
        repo_root / CORRECTION_RELATIVE, view.contract.member_correction_report_sha256
    )
    members = corrected_members(_members(member_file), correction)
    if membership_identity(members) != view.contract.corrected_membership_sha256:
        raise EXQ001Error("actual corrected membership differs from development contract")
    definitions = {
        item.alpha_id: item
        for item in load_af001_registry(
            repo_root / "configs/v2/alphas/af_001_alpha_registry_v1.yaml"
        ).alphas
    }
    lookbacks = {
        alpha: definitions[alpha].lookback_sessions
        for alpha in registry.required_candidate_alpha_ids
    }
    residual_rows = _residual_intersection(
        residual, members, view.contract.sessions, view.access.signal_spans, lookbacks
    )
    interval_rows = intervals.get("intervals")
    if not isinstance(interval_rows, list):
        raise EXQ001Error("free intervals schema lacks intervals")
    relevant_suspensions = sum(
        1
        for row in interval_rows
        if isinstance(row, dict)
        and row.get("symbol") in view.access.symbols
        and date.fromisoformat(str(row["end_session"])) >= view.access.raw_dependency_span.start
        and date.fromisoformat(str(row["start_session"])) <= view.access.raw_dependency_span.end
    )
    dataset_path = repo_root / "configs/v2/datasets/qlib_cn_community_v1.yaml"
    dataset_sha = sha256(dataset_path.read_bytes()).hexdigest()
    dataset = yaml.safe_load(dataset_path.read_text(encoding="utf-8"))
    if (
        not isinstance(dataset, dict)
        or dataset.get("semantics", {}).get("price_type") != "adjusted"
    ):
        raise EXQ001Error("dataset semantics are not the pinned adjusted Qlib declaration")
    blockers = [
        "HISTORICAL_MEMBERSHIP_IS_DERIVATIVE_FIVE_END_BOUNDARY_FIXES_NOT_FULL_PIT",
        "RAW_OHLCV_NOT_IN_APPROVED_DEVELOPMENT_VIEW",
        "CORPORATE_ACTION_EVIDENCE_NOT_OFFICIALLY_VERIFIED",
        "ST_STATUS_NOT_PRESENT_IN_APPROVED_DEVELOPMENT_VIEW",
        "EXECUTION_SEMANTICS_NOT_CAPTURED_FOR_T_PLUS_ONE_PRICE_LIMIT_BOARD_LOT_LIQUIDITY_COSTS",
    ]
    if residual_rows:
        blockers.append("FREE_EVIDENCE_RESIDUAL_INTERSECTS_CANDIDATE_REQUIRED_RANGE")
    return {
        "schema_version": 1,
        "kind": "candidate_scope_qualification",
        "status": "BLOCKED_DATA",
        "scope": "LIMITED_DEV_RESEARCH_CSI300_FROZEN_AF003_CANDIDATES_ONLY",
        "selected_simple_model": registry.required_simple_model,
        "ml_challenger": registry.required_ml_challenger,
        "candidate_alpha_ids": list(registry.required_candidate_alpha_ids),
        "candidate_raw_dependencies": dependencies,
        "required_raw_fields": list(required_raw_fields),
        "label": view.contract.label_expression,
        "label_dependency_offsets": list(view.contract.label_session_offsets),
        "scope_dates": {
            "feature_warmup_and_label_dependency_start": view.access.raw_dependency_span.start.isoformat(),
            "feature_warmup_and_label_dependency_end": view.access.raw_dependency_span.end.isoformat(),
            "signal_spans": [span.model_dump(mode="json") for span in view.access.signal_spans],
        },
        "scope_membership": {
            "symbol_count": len(view.access.symbols),
            "membership_sha256": view.access.membership_sha256,
            "status": "DERIVATIVE_CSI300_MEMBERSHIP_BOUND_NOT_FULL_PIT_QUALIFICATION",
            "limitation": view.contract.membership_limitation,
        },
        "lifecycle_and_suspension": {
            "official_suspension_intervals_intersecting_required_range": relevant_suspensions,
            "free_residual_intersection": residual_rows,
            "free_residual_intersection_count": len(residual_rows),
            "rule": "EXACT_RESIDUAL_KEY_INTERSECTION_WITH_MEMBER_AT_T_FEATURE_LOOKBACK_AND_LABEL_DEPENDENCIES",
        },
        "evidence_matrix": {
            "raw_ohlcv": "BLOCKED_MISSING_RAW_UNADJUSTED_EXECUTION_SOURCE",
            "adjustment_and_corporate_actions": "BLOCKED_NOT_OFFICIALLY_VERIFIED",
            "st_status": "BLOCKED_NOT_IN_APPROVED_VIEW",
            "t_plus_one": "BLOCKED_MISSING_EXECUTION_PRICE_AND_ORDER_SEMANTICS",
            "price_limit": "BLOCKED_MISSING_HISTORICAL_LIMIT_RULE_EVIDENCE",
            "board_lot": "BLOCKED_MISSING_LOT_RULE_EVIDENCE",
            "liquidity": "BLOCKED_MISSING_EXECUTION_LIQUIDITY_SOURCE",
            "costs": "BLOCKED_MISSING_FROZEN_COST_MODEL",
        },
        "blockers": blockers,
        "FORMAL_PIT_STATUS": "BLOCKED_DATA",
        "FORMAL_RESEARCH_STATUS": "BLOCKED_DATA",
        "CSI500": "NOT_STARTED",
        "provenance": {
            "registry_sha256": sha256(registry_path.read_bytes()).hexdigest(),
            "af003_result_sha256": registry.required_af003_result_sha256,
            "dev001_summary_sha256": DEV001_SUMMARY_SHA256,
            "contract_sha256": _string(identities, "contract_sha256"),
            "evidence_sha256": _string(identities, "evidence_sha256"),
            "view_sha256": view.manifest_sha256,
            "dataset_config_sha256": dataset_sha,
            "free_residual_sha256": registry.required_free_residual_sha256,
            "free_intervals_sha256": registry.required_free_intervals_sha256,
            "free_funnel_sha256": registry.required_free_funnel_sha256,
            "code_sha256": sha256(
                (repo_root / "src/quant_stack_v2/exq001.py").read_bytes()
            ).hexdigest(),
            "git_commit": _commit(repo_root),
        },
    }


def persist(payload: dict[str, object], root: Path) -> str:
    """Write the canonical, content-addressed EXQ-001 qualification result."""
    return write_blob(root / "candidate_scope_qualification", canonical(payload))


def render_markdown(payload: dict[str, object], identity: str) -> str:
    """Render an auditable blocked result without disclosure of sealed values."""
    lifecycle = _mapping(payload, "lifecycle_and_suspension")
    lines = [
        "# EXQ-001：冻结候选范围数据资格化",
        "",
        f"状态：`{payload['status']}`；结果 identity：`{identity}`。",
        "",
        "本审计只覆盖 AF-003 冻结的 CSI300 开发候选及其特征预热、信号和标签依赖。它不读取 CSI500，不导出原始行情或封存样本，也不构成全市场、正式 PIT 或正式研究资格结论。",
        "",
        "## 范围与绑定",
        "",
        f"- 简单组合：`{payload['selected_simple_model']}`；机器学习 challenger：`{payload['ml_challenger']}`。",
        f"- 候选：{', '.join(cast(list[str], payload['candidate_alpha_ids']))}。",
        f"- 必要 raw 字段：{', '.join(cast(list[str], payload['required_raw_fields']))}；标签：`{payload['label']}`。",
        f"- 成员符号数：{_mapping(payload, 'scope_membership')['symbol_count']}；成员状态：`{_mapping(payload, 'scope_membership')['status']}`。",
        f"- 与候选所需范围相交的官方停牌区间：{lifecycle['official_suspension_intervals_intersecting_required_range']}；冻结 free residual 交集：{lifecycle['free_residual_intersection_count']}。",
        "",
        "## 结论",
        "",
        "执行所需的 raw OHLCV、官方公司行为、ST、T+1 成交价、涨跌停、整手、流动性和成本证据均未由已批准开发视图提供。开发视图的 adjusted Qlib 价格和有限成员修正不能替代这些证据，因此本候选范围为 `BLOCKED_DATA`。",
        "",
        "`FORMAL_PIT_STATUS=BLOCKED_DATA`、`FORMAL_RESEARCH_STATUS=BLOCKED_DATA`、`CSI500=NOT_STARTED` 保持不变。",
        "",
        "## 最小后续证据（未在本任务补取）",
        "",
        "- 对上述冻结范围提供可复核的原始未复权 OHLCV、复权/公司行为、ST 与历史成员证据；",
        "- 提供冻结的 T+1 成交、涨跌停、整手、流动性与成本规则；",
        "- 若 free residual 交集非零，仅对机器结果列出的交集键补充最小证据。",
    ]
    return "\n".join(lines) + "\n"


def _commit(repo_root: Path) -> str:
    output = subprocess.run(
        ["git", "-C", str(repo_root), "rev-parse", "HEAD"],
        check=True,
        capture_output=True,
        text=True,
    )
    return output.stdout.strip()


def main() -> None:
    """Run the restricted metadata-only EXQ-001 qualification."""
    parser = argparse.ArgumentParser()
    parser.add_argument("--development-root", type=Path, required=True)
    parser.add_argument("--sealed-root", type=Path, required=True)
    parser.add_argument("--repo-root", type=Path, required=True)
    parser.add_argument("--registry", type=Path, required=True)
    parser.add_argument("--result-root", type=Path, required=True)
    parser.add_argument("--report", type=Path, required=True)
    args = parser.parse_args()
    payload = qualify(args.development_root, args.sealed_root, args.repo_root, args.registry)
    identity = persist(payload, args.result_root)
    args.report.write_text(render_markdown(payload, identity), encoding="utf-8")
    print(json.dumps({"result_sha256": identity, "status": payload["status"]}, sort_keys=True))


if __name__ == "__main__":
    main()
