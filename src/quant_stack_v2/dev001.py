# ruff: noqa: E501,RUF001
"""Privileged metadata freeze, Qlib export, and fixed DEV-001 real baseline run."""

from __future__ import annotations

import argparse
import getpass
import inspect
import json
import os
import struct
from datetime import UTC, date, datetime
from hashlib import sha256
from importlib.metadata import version
from pathlib import Path
from typing import cast

import yaml

from quant_stack_v2.dev_contract import Member, Span, canonical, digest, write_blob
from quant_stack_v2.dev_real_contract import (
    AccessScopeManifest,
    Alpha158Spec,
    RealDevContract,
    RealDevEvidence,
    RealModelSpec,
)
from quant_stack_v2.dev_real_staged_runner import StagedRealResult, StagedRealRunner
from quant_stack_v2.dev_real_staged_view import (
    corrected_members,
    export_prediction_inputs,
    export_validation_targets,
    membership_identity,
)

ARCHIVE_SHA256 = "eccf69b778f7147502add9f975115c8f057a04b20b073122d9cad12f31889a7e"
MANIFEST_SHA256 = "bf82990791cdd8b0939ded6af41b9ac3d2cf40192ccf8e0693dfbd9b3955fe2e"
TREE_SHA256 = "a826df48452256f195171155e75835d2bd14803ac6fd9b057ee8ae0a57b6c93f"
CORRECTION_RELATIVE = Path(
    "artifacts/v2/csi_member_reconciliation/"
    "1351f115fea9ab3caa9901fac32cb8877fae855aef6fa8b08ff1dc19de13f000.reconciliation.json"
)
CORRECTION_SHA256 = "1351f115fea9ab3caa9901fac32cb8877fae855aef6fa8b08ff1dc19de13f000"


def run_dev001(sealed_root: Path, development_root: Path, repo_root: Path) -> dict[str, object]:
    """Freeze real identities before target access, export one view, then run two models."""
    started = datetime.now(UTC)
    inputs = _resolve_inputs(sealed_root, repo_root)
    sessions = _calendar(inputs["calendar"])
    source_members = _members(inputs["member_file"])
    correction = _json(inputs["correction"])
    members = corrected_members(source_members, correction)
    _verify_feature_files(inputs["qlib_root"], members, sessions)
    resolved = _resolve_contract(inputs, sessions, members, repo_root)

    authority = development_root / "authority"
    views = development_root / "views"
    results = development_root / "results"
    summaries = development_root / "summaries"
    contract_sha = write_blob(authority, canonical(resolved))
    symbols = tuple(sorted({item.symbol for item in members if _overlaps_run(item)}))
    access = AccessScopeManifest(
        schema_version=1,
        run_id="DEV-001",
        status="FROZEN_BEFORE_TARGET_READ",
        contract_sha256=contract_sha,
        universe="csi300",
        symbols=symbols,
        membership_sha256=resolved.corrected_membership_sha256,
        raw_dependency_span=resolved.raw_dependency_span,
        signal_spans=(resolved.train, resolved.validation),
        alpha158_expression_sha256=resolved.alpha158.expression_sha256,
        raw_fields=resolved.alpha158.raw_dependencies,
        label_field="close",
        label_session_offsets=(1, 2),
        forbidden_roots=("csi500", "sealed_test"),
        target_values_accessed=False,
    )
    access_sha = write_blob(authority, canonical(access))
    evidence = RealDevEvidence(
        schema_version=1,
        kind="real_qlib_limited_dev_scope_verification",
        validator_version="dev001-real-evidence-v1",
        contract_sha256=contract_sha,
        access_scope_sha256=access_sha,
        dataset_config_sha256=resolved.dataset_config_sha256,
        use_config_sha256=resolved.use_config_sha256,
        model_config_sha256=resolved.model_config_sha256,
        archive_sha256=resolved.archive_sha256,
        release_manifest_sha256=resolved.release_manifest_sha256,
        extracted_tree_sha256=resolved.extracted_tree_sha256,
        import_report_sha256=resolved.import_report_sha256,
        factor_semantics_report_sha256=resolved.factor_semantics_report_sha256,
        source_member_file_sha256=resolved.source_member_file_sha256,
        member_correction_report_sha256=resolved.member_correction_report_sha256,
        corrected_membership_sha256=resolved.corrected_membership_sha256,
        calendar_sha256=resolved.calendar_sha256,
        alpha158_expression_sha256=resolved.alpha158.expression_sha256,
        universe="csi300",
        formal_qualification="BLOCKED_DATA",
        sealed_test="NOT_STARTED",
    )
    evidence_sha = write_blob(authority, canonical(evidence))

    # The first target-value access is below. All scope and evidence bytes are now immutable.
    view_sha, view_pin_sha = export_prediction_inputs(
        authority=authority,
        contract_sha256=contract_sha,
        evidence_sha256=evidence_sha,
        members=members,
        provider_uri=inputs["qlib_root"],
        view_root=views,
    )
    runner = StagedRealRunner(
        authority=authority,
        view_root=views,
        result_root=results,
        contract_sha256=contract_sha,
        evidence_sha256=evidence_sha,
        view_pin_sha256=view_pin_sha,
    )
    receipts = [runner.freeze_predictions("linear"), runner.freeze_predictions("lightgbm")]
    target_sha = export_validation_targets(
        authority=authority,
        view_root=views,
        contract_sha256=contract_sha,
        evidence_sha256=evidence_sha,
        view_pin_sha256=view_pin_sha,
        provider_uri=inputs["qlib_root"],
        members=members,
        prediction_receipts=(receipts[0].sha256, receipts[1].sha256),
        result_root=results,
    )
    model_results = [runner.evaluate(receipt.sha256, target_sha) for receipt in receipts]
    summary = _summary(
        resolved,
        contract_sha,
        access_sha,
        evidence_sha,
        view_sha,
        view_pin_sha,
        target_sha,
        tuple(receipt.sha256 for receipt in receipts),
        model_results,
        views,
        started,
    )
    summary_sha = write_blob(summaries, canonical(summary))
    summary["summary_sha256"] = summary_sha
    return summary


def _resolve_inputs(sealed_root: Path, repo_root: Path) -> dict[str, Path]:
    dataset = repo_root / "configs/v2/datasets/qlib_cn_community_v1.yaml"
    use_config = repo_root / "configs/v2/development/dev_001_real_v1.yaml"
    model_config = repo_root / "configs/v2/models/dev_001_models_v1.yaml"
    dataset_payload = yaml.safe_load(dataset.read_text(encoding="utf-8"))
    use_payload = yaml.safe_load(use_config.read_text(encoding="utf-8"))
    model_payload = yaml.safe_load(model_config.read_text(encoding="utf-8"))
    if (
        dataset_payload["artifacts"]["archive_sha256"] != ARCHIVE_SHA256
        or dataset_payload["artifacts"]["manifest_sha256"] != MANIFEST_SHA256
        or use_payload.get("reported_tree_sha256") != TREE_SHA256
        or use_payload.get("run_id") != "DEV-001"
        or use_payload.get("approval_status") != "APPROVED_FOR_THIS_EXACT_DEV_RUN"
        or use_payload.get("formal_qualification") != "BLOCKED_DATA"
        or use_payload.get("sealed_test") != "NOT_STARTED"
        or model_payload.get("run_id") != "DEV-001"
        or model_payload.get("seed") != 0
        or model_payload.get("parameter_search") is not False
    ):
        raise ValueError("tracked Qlib dataset identities differ from DEV-001 pins")
    external = sealed_root / "data/external/qlib_cn_community_v1"
    archive = external / ARCHIVE_SHA256 / "qlib_bin.tar.gz"
    release_manifest = external / MANIFEST_SHA256 / "qlib_bin.manifest.json"
    _require_sha(archive, ARCHIVE_SHA256, "Qlib archive")
    _require_sha(release_manifest, MANIFEST_SHA256, "Qlib release manifest")
    import_root = sealed_root / "artifacts/v2/qlib_import" / ARCHIVE_SHA256
    tree = import_root / "trees" / TREE_SHA256
    if not tree.is_dir():
        raise FileNotFoundError(f"fixed extracted Qlib tree is missing: {tree}")
    qlib_root = _qlib_root(tree)
    calendar = qlib_root / "calendars/day.txt"
    member_file = qlib_root / "instruments/csi300.txt"
    reports = tuple((import_root / "reports").glob("*.json"))
    matching_reports = [
        path
        for path in reports
        if _json(path).get("archive_sha256") == ARCHIVE_SHA256
        and _json(path).get("manifest_sha256") == MANIFEST_SHA256
        and _json(path).get("extracted_tree_sha256") == TREE_SHA256
    ]
    if len(matching_reports) != 1:
        raise ValueError("expected exactly one import report for the fixed Qlib tree")
    semantics = [
        path
        for path in (sealed_root / "data/external/qlib_factor_semantics").glob("*/report.json")
        if _json(path).get("archive_sha256") == ARCHIVE_SHA256
        and _json(path).get("status") == "VERIFIED_FACTOR_SEMANTICS"
    ]
    if len(semantics) != 1:
        raise ValueError("expected exactly one archived factor-semantics report")
    correction = repo_root / CORRECTION_RELATIVE
    if not correction.is_file():
        raise FileNotFoundError(f"archived five-boundary correction is missing: {correction}")
    _require_sha(correction, CORRECTION_SHA256, "archived five-boundary correction")
    correction_payload = _json(correction)
    if (
        correction_payload.get("scope") != "SIX_SYMBOL_END_BOUNDARY_RECONCILIATION_NOT_FULL_PIT"
        or correction_payload.get("membership_gate") != "BLOCKED_DATA"
        or correction_payload.get("raw_member_file_modified") is not False
    ):
        raise ValueError("member correction claim boundary changed")
    expected_member_sha = str(correction_payload.get("reported_full_member_file_sha256"))
    _require_sha(member_file, expected_member_sha, "actual CSI300 member file")
    return {
        "dataset_config": dataset,
        "use_config": use_config,
        "model_config": model_config,
        "archive": archive,
        "release_manifest": release_manifest,
        "tree": tree,
        "qlib_root": qlib_root,
        "calendar": calendar,
        "member_file": member_file,
        "import_report": matching_reports[0],
        "semantics_report": semantics[0],
        "correction": correction,
    }


def _resolve_contract(
    inputs: dict[str, Path],
    sessions: tuple[date, ...],
    members: tuple[Member, ...],
    repo_root: Path,
) -> RealDevContract:
    from lightgbm import LGBMRegressor
    from qlib.contrib.data.handler import Alpha158  # type: ignore[import-untyped]
    from qlib.contrib.data.loader import Alpha158DL  # type: ignore[import-untyped]
    from sklearn.linear_model import LinearRegression  # type: ignore[import-untyped]

    train_candidates = tuple(
        day for day in sessions if date(2015, 1, 1) <= day <= date(2019, 12, 31)
    )
    valid_candidates = tuple(
        day for day in sessions if date(2020, 1, 1) <= day <= date(2020, 12, 31)
    )
    if len(train_candidates) < 63 or len(valid_candidates) < 23:
        raise ValueError("fixed Qlib calendar lacks the DEV-001 candidate ranges")
    positions = {day: index for index, day in enumerate(sessions)}
    warmup_start = sessions[positions[train_candidates[0]] - 60]
    alpha = object.__new__(Alpha158)
    expressions, names = Alpha158.get_feature_config(alpha)
    expression_sha = digest({"names": names, "expressions": expressions})
    handler_path = Path(cast(str, inspect.getsourcefile(Alpha158)))
    loader_path = Path(cast(str, inspect.getsourcefile(Alpha158DL)))
    linear = LinearRegression(fit_intercept=True, n_jobs=1)
    lightgbm = LGBMRegressor(
        objective="regression",
        n_estimators=200,
        learning_rate=0.05,
        num_leaves=31,
        max_depth=6,
        min_child_samples=100,
        subsample=1.0,
        subsample_freq=0,
        colsample_bytree=1.0,
        reg_alpha=0.0,
        reg_lambda=0.0,
        random_state=0,
        n_jobs=1,
        device_type="cpu",
        deterministic=True,
        force_col_wise=True,
        verbosity=-1,
    )
    model_config = yaml.safe_load(inputs["model_config"].read_text(encoding="utf-8"))
    expected_models = {
        "linear": linear.get_params(deep=False),
        "lightgbm": lightgbm.get_params(deep=False),
    }
    if model_config.get("models") != expected_models:
        raise ValueError("tracked DEV-001 model config differs from locked effective parameters")
    code_paths = [
        repo_root / "src/quant_stack_v2/dev001.py",
        repo_root / "src/quant_stack_v2/dev_real_contract.py",
        repo_root / "src/quant_stack_v2/dev_real_staged_view.py",
        repo_root / "src/quant_stack_v2/dev_real_staged_runner.py",
    ]
    code_sha = digest({path.name: _file_sha(path) for path in code_paths})
    train_end = train_candidates[-3]
    valid_end = valid_candidates[-3]
    valid_start = valid_candidates[20]
    return RealDevContract(
        schema_version=1,
        contract_kind="LIMITED_DEV_RESEARCH_REAL_V1",
        run_id="DEV-001",
        status="FROZEN_BEFORE_TARGET_READ",
        data_kind="QLIB_CN_COMMUNITY",
        universe="csi300",
        formal_qualification="BLOCKED_DATA",
        sealed_test="NOT_STARTED",
        dataset_id="qlib_cn_community_v1",
        dataset_config_sha256=_file_sha(inputs["dataset_config"]),
        use_config_sha256=_file_sha(inputs["use_config"]),
        model_config_sha256=_file_sha(inputs["model_config"]),
        archive_sha256=_file_sha(inputs["archive"]),
        release_manifest_sha256=_file_sha(inputs["release_manifest"]),
        extracted_tree_sha256=TREE_SHA256,
        import_report_sha256=_file_sha(inputs["import_report"]),
        factor_semantics_report_sha256=_file_sha(inputs["semantics_report"]),
        source_member_file_sha256=_file_sha(inputs["member_file"]),
        member_correction_report_sha256=_file_sha(inputs["correction"]),
        corrected_membership_sha256=membership_identity(members),
        membership_limitation="FIVE_END_BOUNDARY_FIXES_NOT_FULL_PIT_QUALIFICATION",
        calendar_sha256=_file_sha(inputs["calendar"]),
        sessions=sessions,
        raw_dependency_span=Span(start=warmup_start, end=valid_candidates[-1]),
        train_candidate=Span(start=train_candidates[0], end=train_candidates[-1]),
        train=Span(start=train_candidates[0], end=train_end),
        validation_candidate=Span(start=valid_candidates[0], end=valid_candidates[-1]),
        validation=Span(start=valid_start, end=valid_end),
        validation_excluded_head_sessions=valid_candidates[:20],
        train_label_dependency_end=train_candidates[-1],
        validation_label_dependency_end=valid_candidates[-1],
        label_expression="close[T+2] / close[T+1] - 1",
        label_session_offsets=(1, 2),
        preprocessing="TRAIN_FIT_STANDARD_SCALER_COMPLETE_ALPHA158_FEATURES",
        preprocessing_params={
            "copy": True,
            "with_mean": True,
            "with_std": True,
            "transform_output": "pandas",
        },
        prediction_eligibility="MEMBER_AT_T_AND_COMPLETE_FEATURES_INDEPENDENT_OF_FUTURE_LABEL",
        alpha158=Alpha158Spec(
            pyqlib_version="0.9.7",
            names=tuple(names),
            expressions=tuple(expressions),
            handler_source_sha256=_file_sha(handler_path),
            loader_source_sha256=_file_sha(loader_path),
            expression_sha256=expression_sha,
            raw_dependencies=("open", "high", "low", "close", "vwap", "volume"),
            warmup_sessions=60,
        ),
        diagnostic_segments=_quarter_segments(valid_candidates, valid_start, valid_end),
        models=(
            RealModelSpec(kind="linear", seed=0, params=linear.get_params(deep=False)),
            RealModelSpec(kind="lightgbm", seed=0, params=lightgbm.get_params(deep=False)),
        ),
        runtime_versions={
            package: version(package)
            for package in ("pyqlib", "lightgbm", "scikit-learn", "pandas", "pyarrow")
        },
        code_sha256=code_sha,
    )


def _summary(
    contract: RealDevContract,
    contract_sha: str,
    access_sha: str,
    evidence_sha: str,
    view_sha: str,
    view_pin_sha: str,
    target_sha: str,
    prediction_receipts: tuple[str, ...],
    results: list[StagedRealResult],
    view_root: Path,
    started: datetime,
) -> dict[str, object]:
    view_manifest = _json(view_root / view_sha / "manifest.json")
    return {
        "schema_version": 1,
        "run_id": "DEV-001",
        "status": "DEV_REAL_RUN_COMPLETED",
        "usage": "LIMITED_DEV_RESEARCH",
        "formal_research": "BLOCKED_DATA",
        "csi500": "NOT_STARTED",
        "started_at_utc": started.isoformat(),
        "completed_at_utc": datetime.now(UTC).isoformat(),
        "execution_account": getpass.getuser(),
        "sudo_invoking_uid": os.environ.get("SUDO_UID"),
        "identities": {
            "contract_sha256": contract_sha,
            "access_scope_sha256": access_sha,
            "evidence_sha256": evidence_sha,
            "view_sha256": view_sha,
            "dataset_config_sha256": contract.dataset_config_sha256,
            "use_config_sha256": contract.use_config_sha256,
            "model_config_sha256": contract.model_config_sha256,
            "view_pin_sha256": view_pin_sha,
            "validation_target_sha256": target_sha,
            "prediction_receipt_sha256": prediction_receipts,
            "archive_sha256": contract.archive_sha256,
            "release_manifest_sha256": contract.release_manifest_sha256,
            "tree_sha256": contract.extracted_tree_sha256,
            "member_file_sha256": contract.source_member_file_sha256,
            "corrected_membership_sha256": contract.corrected_membership_sha256,
            "code_sha256": contract.code_sha256,
            "alpha158_expression_sha256": contract.alpha158.expression_sha256,
        },
        "boundaries": {
            "raw_dependency": contract.raw_dependency_span.model_dump(mode="json"),
            "train_candidate": contract.train_candidate.model_dump(mode="json"),
            "train": contract.train.model_dump(mode="json"),
            "validation_candidate": contract.validation_candidate.model_dump(mode="json"),
            "validation": contract.validation.model_dump(mode="json"),
            "validation_excluded_head_sessions": [
                day.isoformat() for day in contract.validation_excluded_head_sessions
            ],
            "train_label_dependency_end": contract.train_label_dependency_end.isoformat(),
            "validation_label_dependency_end": contract.validation_label_dependency_end.isoformat(),
        },
        "view": {
            "total_rows": view_manifest["total_feature_rows"],
            "exclusions": view_manifest["exclusions"],
            "shards": view_manifest["shards"],
        },
        "models": [result.__dict__ for result in results],
        "limitations": [
            "CSI300 membership uses the archived source plus five end-boundary fixes; full PIT qualification remains blocked.",
            "Qlib prices are adjusted under the archived factor-semantics evidence; no comprehensive raw-price reconciliation is claimed.",
            "The touched development period is not a fresh holdout and the results are exposed to selection and survivorship limitations in the source membership history.",
            "Metrics are signal diagnostics only; no CAGR, Sharpe, portfolio return, tradability, promotion, or live-trading claim is made.",
        ],
    }


def render_markdown(summary: dict[str, object]) -> str:
    """Render the concise committed DEV-001 report from the actual machine summary."""
    identities = cast(dict[str, str], summary["identities"])
    boundaries = cast(dict[str, object], summary["boundaries"])
    view = cast(dict[str, object], summary["view"])
    models = cast(list[dict[str, object]], summary["models"])
    lines = [
        "# DEV-001：第一次真实CSI300开发基线",
        "",
        f"状态：**{summary['status']}**。用途仅为`LIMITED_DEV_RESEARCH`；正式研究仍为`{summary['formal_research']}`，CSI500为`{summary['csi500']}`。",
        "",
        "## 身份与边界",
        "",
        f"- archive：`{identities['archive_sha256']}`；tree：`{identities['tree_sha256']}`。",
        f"- 数据、使用范围和模型配置：`{identities['dataset_config_sha256']}`、`{identities['use_config_sha256']}`、`{identities['model_config_sha256']}`。",
        f"- resolved contract：`{identities['contract_sha256']}`；evidence：`{identities['evidence_sha256']}`；view：`{identities['view_sha256']}`。",
        f"- 机器摘要：`/srv/quant-v2/development/dev001/summaries/{summary['summary_sha256']}.json`。",
        f"- Alpha158表达式：`{identities['alpha158_expression_sha256']}`；代码：`{identities['code_sha256']}`。",
        f"- 训练：`{boundaries['train']}`；验证：`{boundaries['validation']}`；验证首20个交易日已排除。",
        f"- 开发视图共{view['total_rows']}行，分片与排除统计保存在同一机器结果中。",
        "",
        "## 固定模型结果",
        "",
        "| 模型 | 训练样本 | 预测样本 | 评价样本 | MSE | 日横截面IC | Rank IC | 重载/重建 |",
        "| --- | ---: | ---: | ---: | ---: | ---: | ---: | --- |",
    ]
    for model in models:
        lines.append(
            f"| {model['model']} | {model['training_rows']} | {model['prediction_rows']} | {model['evaluated_rows']} | "
            f"{_fmt(model['mse'])} | {_fmt(model['daily_ic'])} | {_fmt(model['daily_rank_ic'])} | 精确一致 |"
        )
    lines += [
        "",
        "模型结果manifest分别为"
        f"Linear `{models[0]['manifest_sha256']}`、"
        f"LightGBM `{models[1]['manifest_sha256']}`。",
    ]
    exclusions = cast(dict[str, dict[str, int]], view["exclusions"])
    lines += ["", "## 样本与缺失", ""]
    for split in ("train", "validation"):
        item = exclusions[split]
        ratio = (
            item["missing_feature_cells"] / item["feature_cells"] if item["feature_cells"] else 0.0
        )
        label_missing = item["missing_label_rows"]
        if split == "validation" and models:
            label_missing = cast(int, models[0]["prediction_rows"]) - cast(
                int, models[0]["evaluated_rows"]
            )
        lines.append(
            f"- {split}: member-at-T {item['member_signal_rows']}行, "
            f"整行缺失 {item['missing_source_rows']}, 特征不完整排除 "
            f"{item['incomplete_feature_rows']}, 完整特征 {item['complete_feature_rows']}, "
            f"标签缺失 {label_missing}, 特征单元缺失率 {ratio:.6%}。"
        )
    lines += ["", "## 固定季度诊断", ""]
    for model in models:
        lines += [
            f"### {model['model']}",
            "",
            "| 区间 | 评价样本 | MSE | 日横截面IC | Rank IC |",
            "| --- | ---: | ---: | ---: | ---: |",
        ]
        segments = cast(dict[str, dict[str, object]], model["time_segments"])
        for name, metrics in segments.items():
            lines.append(
                f"| {name} | {metrics['evaluated_rows']} | {_fmt(metrics['mse'])} | "
                f"{_fmt(metrics['daily_ic'])} | {_fmt(metrics['daily_rank_ic'])} |"
            )
        lines.append("")
    lines += [
        "",
        "固定季度分段诊断、缺失比例、逐项排除原因及未定义指标原因保存在内容寻址机器结果与两个模型结果中。未实施组合实验，因此不报告CAGR、Sharpe或可交易收益。IC为正也不构成Alpha发现或晋级结论。",
        "",
        "## 工程重放记录",
        "",
        "1. 首次执行在解析受限使用YAML时失败，发生在任何目标值读取前；修复仅为给标签公式加引号，并增加配置解析回归测试。",
        "2. 第二次执行在训练视图投影时错误拒绝了特征不完整样本对应的合法标签行，"
        "发生在模型训练和验证标签开放前；修复为先校验完整成员日期网格，再按完整特征键筛选标签。"
        "模型参数、日期、数据源和成员规则未改变。",
        "3. 最终执行完成两模型训练、预测冻结、验证标签开放、评价、模型重载和独立预测重建，状态为`DEV_REAL_RUN_COMPLETED`。",
        "",
        "## 已知限制",
        "",
        "成员历史仅叠加已归档的五项终点修正，完整PIT资格仍为`BLOCKED_DATA`。价格为Qlib归一化后的复权语义，本次哈希与源码证据限定开发用途，不冒充完整原始行情对账。验证期已被本次开发读取，不是未接触holdout；结果仍受成员、复权与选择偏差限制。",
        "",
    ]
    return "\n".join(lines)


def _quarter_segments(sessions: tuple[date, ...], start: date, end: date) -> tuple[Span, ...]:
    spans: list[Span] = []
    for left, right in (
        (date(2020, 1, 1), date(2020, 3, 31)),
        (date(2020, 4, 1), date(2020, 6, 30)),
        (date(2020, 7, 1), date(2020, 9, 30)),
        (date(2020, 10, 1), date(2020, 12, 31)),
    ):
        available = [day for day in sessions if start <= day <= end and left <= day <= right]
        if available:
            spans.append(Span(start=available[0], end=available[-1]))
    return tuple(spans)


def _calendar(path: Path) -> tuple[date, ...]:
    sessions = tuple(
        date.fromisoformat(line.strip()) for line in path.read_text().splitlines() if line.strip()
    )
    if not sessions or sessions != tuple(sorted(set(sessions))):
        raise ValueError("Qlib calendar is not ordered and unique")
    return sessions


def _members(path: Path) -> tuple[Member, ...]:
    result: list[Member] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        fields = line.split("\t")
        if len(fields) != 3:
            raise ValueError("CSI300 member file has an invalid record")
        result.append(
            Member(
                symbol=fields[0].lower(),
                start=date.fromisoformat(fields[1]),
                end=date.fromisoformat(fields[2]),
            )
        )
    if not result:
        raise ValueError("CSI300 member file is empty")
    return tuple(result)


def _overlaps_run(member: Member) -> bool:
    return member.start <= date(2020, 12, 31) and member.end >= date(2015, 1, 1)


def _verify_feature_files(
    qlib_root: Path, members: tuple[Member, ...], sessions: tuple[date, ...]
) -> None:
    """Verify only CSI300 raw dependency files and their calendar-index headers."""
    symbols = sorted({member.symbol for member in members if _overlaps_run(member)})
    missing: list[str] = []
    invalid_headers: list[str] = []
    fields = ("open", "high", "low", "close", "vwap", "volume")
    for symbol in symbols:
        directory = qlib_root / "features" / symbol
        for field in fields:
            path = directory / f"{field}.day.bin"
            if not path.is_file():
                missing.append(f"{symbol}:{field}")
                continue
            with path.open("rb") as handle:
                header = handle.read(4)
            if len(header) != 4:
                invalid_headers.append(f"{symbol}:{field}:short")
                continue
            offset = struct.unpack("<f", header)[0]
            if not offset.is_integer() or not 0 <= int(offset) < len(sessions):
                invalid_headers.append(f"{symbol}:{field}:{offset}")
    if missing:
        raise ValueError("required CSI300 Qlib fields are missing: " + ",".join(missing[:20]))
    if invalid_headers:
        raise ValueError(
            "Qlib binary calendar headers are invalid: " + ",".join(invalid_headers[:20])
        )


def _qlib_root(tree: Path) -> Path:
    """Resolve only the two fixed archive layouts without scanning the sealed tree."""
    candidates = tuple(
        candidate
        for candidate in (tree, tree / "qlib_bin")
        if (candidate / "calendars/day.txt").is_file()
    )
    if len(candidates) != 1:
        raise ValueError("expected one fixed Qlib root layout")
    return candidates[0]


def _require_sha(path: Path, expected: str, label: str) -> None:
    if not path.is_file() or _file_sha(path) != expected:
        raise ValueError(f"{label} does not match fixed SHA-256")


def _file_sha(path: Path) -> str:
    value = sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(1024 * 1024):
            value.update(chunk)
    return value.hexdigest()


def _json(path: Path) -> dict[str, object]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"expected JSON object: {path}")
    return cast(dict[str, object], value)


def _fmt(value: object) -> str:
    return "未定义" if value is None else f"{float(cast(float, value)):.8g}"


def main() -> None:
    """Execute the single fixed host-side DEV-001 workflow."""
    parser = argparse.ArgumentParser()
    parser.add_argument("--sealed-root", type=Path, required=True)
    parser.add_argument("--development-root", type=Path, required=True)
    parser.add_argument("--repo-root", type=Path, required=True)
    parser.add_argument("--report", type=Path, required=True)
    args = parser.parse_args()
    summary = run_dev001(args.sealed_root, args.development_root, args.repo_root)
    report_body = render_markdown(summary).encode()
    temporary = args.report.with_name(args.report.name + ".stage")
    temporary.write_bytes(report_body)
    temporary.replace(args.report)
    print(json.dumps(summary, sort_keys=True))


if __name__ == "__main__":
    main()
