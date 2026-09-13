"""Versioned contract and immutable identities for a real limited Qlib dev run."""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path
from typing import Any, Literal

from pydantic import model_validator

from quant_stack_v2.dev_contract import Digest, Span, StrictModel, canonical, digest, read_blob

ALPHA158_V097_SHA256 = "2e3607d5e4fca26ee901c8d97ec692d5427b2332fe509eda8288e218ddcda92d"


class RealModelSpec(StrictModel):
    """One fixed estimator with every effective constructor parameter expanded."""

    kind: Literal["linear", "lightgbm"]
    seed: Literal[0]
    params: dict[str, bool | int | float | str | None]


class Alpha158Spec(StrictModel):
    """Exact pyqlib Alpha158 expression and implementation identity."""

    pyqlib_version: Literal["0.9.7"]
    names: tuple[str, ...]
    expressions: tuple[str, ...]
    handler_source_sha256: Digest
    loader_source_sha256: Digest
    expression_sha256: Digest
    raw_dependencies: tuple[Literal["open", "high", "low", "close", "vwap", "volume"], ...]
    warmup_sessions: Literal[60]

    @model_validator(mode="after")
    def complete_alpha158(self) -> Alpha158Spec:
        if len(self.names) != 158 or len(self.expressions) != 158:
            raise ValueError("standard Alpha158 must contain exactly 158 named expressions")
        if len(set(self.names)) != 158:
            raise ValueError("Alpha158 feature names must be unique")
        if self.raw_dependencies != ("open", "high", "low", "close", "vwap", "volume"):
            raise ValueError("Alpha158 raw dependency allowlist changed")
        if (
            self.expression_sha256
            != digest({"names": list(self.names), "expressions": list(self.expressions)})
            or self.expression_sha256 != ALPHA158_V097_SHA256
        ):
            raise ValueError("Alpha158 expression identity mismatch")
        return self


class RealDevContract(StrictModel):
    """Resolved, executable contract for only the authorized CSI300 development run."""

    schema_version: Literal[1]
    contract_kind: Literal["LIMITED_DEV_RESEARCH_REAL_V1"]
    run_id: Literal["DEV-001"]
    status: Literal["FROZEN_BEFORE_TARGET_READ"]
    data_kind: Literal["QLIB_CN_COMMUNITY"]
    universe: Literal["csi300"]
    formal_qualification: Literal["BLOCKED_DATA"]
    sealed_test: Literal["NOT_STARTED"]
    dataset_id: Literal["qlib_cn_community_v1"]
    dataset_config_sha256: Digest
    use_config_sha256: Digest
    model_config_sha256: Digest
    archive_sha256: Digest
    release_manifest_sha256: Digest
    extracted_tree_sha256: Digest
    import_report_sha256: Digest
    factor_semantics_report_sha256: Digest
    source_member_file_sha256: Digest
    member_correction_report_sha256: Digest
    corrected_membership_sha256: Digest
    membership_limitation: Literal["FIVE_END_BOUNDARY_FIXES_NOT_FULL_PIT_QUALIFICATION"]
    calendar_sha256: Digest
    sessions: tuple[date, ...]
    raw_dependency_span: Span
    train_candidate: Span
    train: Span
    validation_candidate: Span
    validation: Span
    validation_excluded_head_sessions: tuple[date, ...]
    train_label_dependency_end: date
    validation_label_dependency_end: date
    label_expression: Literal["close[T+2] / close[T+1] - 1"]
    label_session_offsets: tuple[Literal[1], Literal[2]]
    preprocessing: Literal["TRAIN_FIT_STANDARD_SCALER_COMPLETE_ALPHA158_FEATURES"]
    preprocessing_params: dict[str, bool | str]
    prediction_eligibility: Literal["MEMBER_AT_T_AND_COMPLETE_FEATURES_INDEPENDENT_OF_FUTURE_LABEL"]
    alpha158: Alpha158Spec
    diagnostic_segments: tuple[Span, ...]
    models: tuple[RealModelSpec, ...]
    runtime_versions: dict[str, str]
    code_sha256: Digest

    @model_validator(mode="after")
    def exact_scope(self) -> RealDevContract:
        if not self.sessions or tuple(sorted(set(self.sessions))) != self.sessions:
            raise ValueError("resolved calendar must be ordered and unique")
        valid_candidates = tuple(
            day for day in self.sessions if date(2020, 1, 1) <= day <= date(2020, 12, 31)
        )
        train_candidates = tuple(
            day for day in self.sessions if date(2015, 1, 1) <= day <= date(2019, 12, 31)
        )
        if len(valid_candidates) < 23 or len(train_candidates) < 3:
            raise ValueError("resolved calendar does not contain fixed candidate ranges")
        if self.train_candidate != Span(
            start=train_candidates[0], end=train_candidates[-1]
        ) or self.validation_candidate != Span(start=valid_candidates[0], end=valid_candidates[-1]):
            raise ValueError("candidate spans are not mechanically resolved")
        if self.validation_excluded_head_sessions != valid_candidates[:20]:
            raise ValueError("validation must exclude exactly its first 20 sessions")
        if self.validation.start != valid_candidates[20]:
            raise ValueError("validation does not start at the 21st candidate session")
        if self.train != Span(start=train_candidates[0], end=train_candidates[-3]):
            raise ValueError("training sample boundary is not mechanically resolved")
        if self.validation != Span(start=valid_candidates[20], end=valid_candidates[-3]):
            raise ValueError("validation sample boundary is not mechanically resolved")
        if self.train_label_dependency_end != train_candidates[-1]:
            raise ValueError("training label dependency boundary changed")
        if self.validation_label_dependency_end != valid_candidates[-1]:
            raise ValueError("validation label dependency boundary changed")
        if self.train.end >= self.validation.start:
            raise ValueError("training and validation overlap")
        positions = {day: index for index, day in enumerate(self.sessions)}
        for boundary in (
            self.raw_dependency_span.start,
            self.raw_dependency_span.end,
            self.train_candidate.start,
            self.train_candidate.end,
            self.train.start,
            self.train.end,
            self.validation_candidate.start,
            self.validation_candidate.end,
            self.validation.start,
            self.validation.end,
            self.train_label_dependency_end,
            self.validation_label_dependency_end,
        ):
            if boundary not in positions:
                raise ValueError("all resolved boundaries must be trading sessions")
        if positions[self.train_candidate.start] - positions[self.raw_dependency_span.start] != 60:
            raise ValueError("raw dependency span must provide exactly 60 warm-up sessions")
        if self.raw_dependency_span.end != self.validation_label_dependency_end:
            raise ValueError("raw dependency span does not end at validation label boundary")
        if positions[self.train.end] + 2 != positions[self.train_label_dependency_end]:
            raise ValueError("training label tail is not exactly T+2")
        if positions[self.validation.end] + 2 != positions[self.validation_label_dependency_end]:
            raise ValueError("validation label tail is not exactly T+2")
        if len(self.models) != 2 or {model.kind for model in self.models} != {
            "linear",
            "lightgbm",
        }:
            raise ValueError("DEV-001 requires exactly Linear and LightGBM")
        linear = next(model for model in self.models if model.kind == "linear")
        lightgbm = next(model for model in self.models if model.kind == "lightgbm")
        if linear.params != {
            "copy_X": True,
            "fit_intercept": True,
            "n_jobs": 1,
            "positive": False,
            "tol": 0.000001,
        }:
            raise ValueError("Linear parameters differ from DEV-001")
        required_lgbm: dict[str, object] = {
            "objective": "regression",
            "n_estimators": 200,
            "learning_rate": 0.05,
            "num_leaves": 31,
            "max_depth": 6,
            "min_child_samples": 100,
            "subsample": 1.0,
            "subsample_freq": 0,
            "colsample_bytree": 1.0,
            "reg_alpha": 0.0,
            "reg_lambda": 0.0,
            "random_state": 0,
            "n_jobs": 1,
            "device_type": "cpu",
            "deterministic": True,
            "force_col_wise": True,
            "verbosity": -1,
        }
        required_lgbm.update(
            {
                "boosting_type": "gbdt",
                "class_weight": None,
                "importance_type": "split",
                "min_child_weight": 0.001,
                "min_split_gain": 0.0,
                "subsample_for_bin": 200000,
            }
        )
        if lightgbm.params != required_lgbm:
            raise ValueError("LightGBM parameters differ from DEV-001")
        if self.preprocessing_params != {
            "copy": True,
            "with_mean": True,
            "with_std": True,
            "transform_output": "pandas",
        }:
            raise ValueError("StandardScaler parameters differ from DEV-001")
        quarters: list[Span] = []
        for left, right in (
            (date(2020, 1, 1), date(2020, 3, 31)),
            (date(2020, 4, 1), date(2020, 6, 30)),
            (date(2020, 7, 1), date(2020, 9, 30)),
            (date(2020, 10, 1), date(2020, 12, 31)),
        ):
            available = [day for day in valid_candidates[20:-2] if left <= day <= right]
            if available:
                quarters.append(Span(start=available[0], end=available[-1]))
        if self.diagnostic_segments != tuple(quarters):
            raise ValueError("diagnostic segments are not fixed 2020 calendar quarters")
        if (
            self.runtime_versions.get("pyqlib") != "0.9.7"
            or self.runtime_versions.get("lightgbm") != "4.5.0"
        ):
            raise ValueError("locked model runtime versions changed")
        return self


class AccessScopeManifest(StrictModel):
    """Planned privileged read range, frozen before any feature or label values are read."""

    schema_version: Literal[1]
    run_id: Literal["DEV-001"]
    status: Literal["FROZEN_BEFORE_TARGET_READ"]
    contract_sha256: Digest
    universe: Literal["csi300"]
    symbols: tuple[str, ...]
    membership_sha256: Digest
    raw_dependency_span: Span
    signal_spans: tuple[Span, Span]
    alpha158_expression_sha256: Digest
    raw_fields: tuple[str, ...]
    label_field: Literal["close"]
    label_session_offsets: tuple[Literal[1], Literal[2]]
    forbidden_roots: tuple[Literal["csi500"], Literal["sealed_test"]]
    target_values_accessed: Literal[False]


class RealDevEvidence(StrictModel):
    """Actual byte identities backing one resolved limited-use contract."""

    schema_version: Literal[1]
    kind: Literal["real_qlib_limited_dev_scope_verification"]
    validator_version: Literal["dev001-real-evidence-v1"]
    contract_sha256: Digest
    access_scope_sha256: Digest
    dataset_config_sha256: Digest
    use_config_sha256: Digest
    model_config_sha256: Digest
    archive_sha256: Digest
    release_manifest_sha256: Digest
    extracted_tree_sha256: Digest
    import_report_sha256: Digest
    factor_semantics_report_sha256: Digest
    source_member_file_sha256: Digest
    member_correction_report_sha256: Digest
    corrected_membership_sha256: Digest
    calendar_sha256: Digest
    alpha158_expression_sha256: Digest
    universe: Literal["csi300"]
    formal_qualification: Literal["BLOCKED_DATA"]
    sealed_test: Literal["NOT_STARTED"]


class RealViewPin(StrictModel):
    """Exporter-owned approval of the one real view accepted downstream."""

    schema_version: Literal[1]
    kind: Literal["dev001_real_view_pin"]
    contract_sha256: Digest
    evidence_sha256: Digest
    view_sha256: Digest


def load_real_contract(authority: Path, identity: str) -> RealDevContract:
    """Load an exact hash-named resolved real-development contract."""
    return RealDevContract.model_validate_json(read_blob(authority, identity))


def load_real_evidence(
    authority: Path, contract_sha256: str, evidence_sha256: str
) -> tuple[RealDevContract, RealDevEvidence, AccessScopeManifest]:
    """Reopen and validate the complete real contract, evidence, and pre-read scope chain."""
    contract = load_real_contract(authority, contract_sha256)
    evidence = RealDevEvidence.model_validate_json(read_blob(authority, evidence_sha256))
    access = AccessScopeManifest.model_validate_json(
        read_blob(authority, evidence.access_scope_sha256)
    )
    if evidence.contract_sha256 != contract_sha256 or access.contract_sha256 != contract_sha256:
        raise ValueError("real development evidence is cross-contract")
    bindings: dict[str, Any] = {
        "dataset_config_sha256": contract.dataset_config_sha256,
        "use_config_sha256": contract.use_config_sha256,
        "model_config_sha256": contract.model_config_sha256,
        "archive_sha256": contract.archive_sha256,
        "release_manifest_sha256": contract.release_manifest_sha256,
        "extracted_tree_sha256": contract.extracted_tree_sha256,
        "import_report_sha256": contract.import_report_sha256,
        "factor_semantics_report_sha256": contract.factor_semantics_report_sha256,
        "source_member_file_sha256": contract.source_member_file_sha256,
        "member_correction_report_sha256": contract.member_correction_report_sha256,
        "corrected_membership_sha256": contract.corrected_membership_sha256,
        "calendar_sha256": contract.calendar_sha256,
        "alpha158_expression_sha256": contract.alpha158.expression_sha256,
    }
    for name, expected in bindings.items():
        if getattr(evidence, name) != expected:
            raise ValueError("real development evidence mismatch: " + name)
    if access.membership_sha256 != contract.corrected_membership_sha256:
        raise ValueError("access scope membership mismatch")
    if access.alpha158_expression_sha256 != contract.alpha158.expression_sha256:
        raise ValueError("access scope Alpha158 mismatch")
    if (
        access.raw_dependency_span != contract.raw_dependency_span
        or access.signal_spans != (contract.train, contract.validation)
        or access.raw_fields != contract.alpha158.raw_dependencies
        or access.label_session_offsets != contract.label_session_offsets
        or access.forbidden_roots != ("csi500", "sealed_test")
        or access.target_values_accessed is not False
    ):
        raise ValueError("access scope dates, fields, or label offsets mismatch")
    return contract, evidence, access


def canonical_json_file(path: Path) -> bytes:
    """Canonicalize an existing JSON evidence file without trusting its filename."""
    value = json.loads(path.read_text(encoding="utf-8"))
    return canonical(value)
