"""Offline staged smoke for the DEV-001 real-view control flow."""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import pytest

import quant_stack_v2.dev_real_staged_view as view_module
from quant_stack_v2.dev_contract import Member, Span, canonical, digest, read_blob, write_blob
from quant_stack_v2.dev_real_contract import (
    AccessScopeManifest,
    Alpha158Spec,
    RealDevContract,
    RealDevEvidence,
    RealModelSpec,
)
from quant_stack_v2.dev_real_staged_runner import StagedRealRunner
from quant_stack_v2.dev_real_staged_view import (
    LABEL_COLUMN,
    _read_qlib,
    export_prediction_inputs,
    export_validation_targets,
    membership_identity,
)


@pytest.fixture(autouse=True)
def forbid_network(monkeypatch: pytest.MonkeyPatch) -> None:
    """The staged real adapter tests cannot use network or DNS."""

    def denied(*args: Any, **kwargs: Any) -> None:
        raise AssertionError("DEV-001 tests must remain offline")

    monkeypatch.setattr("socket.socket.connect", denied)
    monkeypatch.setattr("socket.socket.connect_ex", denied)
    monkeypatch.setattr("socket.create_connection", denied)
    monkeypatch.setattr("socket.getaddrinfo", denied)


def _fixture(tmp_path: Path) -> tuple[Path, Path, Path, Path, tuple[Member, ...], str, str]:
    from lightgbm import LGBMRegressor
    from qlib.contrib.data.handler import Alpha158
    from sklearn.linear_model import LinearRegression

    sessions = tuple(pd.bdate_range("2014-10-09", "2020-12-31").date)
    train_candidates = tuple(
        day for day in sessions if date(2015, 1, 1) <= day <= date(2019, 12, 31)
    )
    valid_candidates = tuple(
        day for day in sessions if date(2020, 1, 1) <= day <= date(2020, 12, 31)
    )
    quarter_spans = tuple(
        Span(start=available[0], end=available[-1])
        for left, right in (
            (date(2020, 1, 1), date(2020, 3, 31)),
            (date(2020, 4, 1), date(2020, 6, 30)),
            (date(2020, 7, 1), date(2020, 9, 30)),
            (date(2020, 10, 1), date(2020, 12, 31)),
        )
        if (available := [day for day in valid_candidates[20:-2] if left <= day <= right])
    )
    expressions, names = Alpha158.get_feature_config(object.__new__(Alpha158))
    members = tuple(
        Member(symbol=symbol, start=train_candidates[0], end=valid_candidates[-1])
        for symbol in ("sh600001", "sz000001", "sz000002")
    )
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
    contract = RealDevContract(
        schema_version=1,
        contract_kind="LIMITED_DEV_RESEARCH_REAL_V1",
        run_id="DEV-001",
        status="FROZEN_BEFORE_TARGET_READ",
        data_kind="QLIB_CN_COMMUNITY",
        universe="csi300",
        formal_qualification="BLOCKED_DATA",
        sealed_test="NOT_STARTED",
        dataset_id="qlib_cn_community_v1",
        dataset_config_sha256="6" * 64,
        use_config_sha256="7" * 64,
        model_config_sha256="8" * 64,
        archive_sha256="a" * 64,
        release_manifest_sha256="b" * 64,
        extracted_tree_sha256="c" * 64,
        import_report_sha256="d" * 64,
        factor_semantics_report_sha256="e" * 64,
        source_member_file_sha256="f" * 64,
        member_correction_report_sha256="1" * 64,
        corrected_membership_sha256=membership_identity(members),
        membership_limitation="FIVE_END_BOUNDARY_FIXES_NOT_FULL_PIT_QUALIFICATION",
        calendar_sha256="2" * 64,
        sessions=sessions,
        raw_dependency_span=Span(
            start=sessions[sessions.index(train_candidates[0]) - 60], end=valid_candidates[-1]
        ),
        train_candidate=Span(start=train_candidates[0], end=train_candidates[-1]),
        train=Span(start=train_candidates[0], end=train_candidates[-3]),
        validation_candidate=Span(start=valid_candidates[0], end=valid_candidates[-1]),
        validation=Span(start=valid_candidates[20], end=valid_candidates[-3]),
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
            handler_source_sha256="3" * 64,
            loader_source_sha256="4" * 64,
            expression_sha256=digest({"names": names, "expressions": expressions}),
            raw_dependencies=("open", "high", "low", "close", "vwap", "volume"),
            warmup_sessions=60,
        ),
        diagnostic_segments=quarter_spans,
        models=(
            RealModelSpec(kind="linear", seed=0, params=linear.get_params(deep=False)),
            RealModelSpec(kind="lightgbm", seed=0, params=lightgbm.get_params(deep=False)),
        ),
        runtime_versions={"pyqlib": "0.9.7", "lightgbm": "4.5.0"},
        code_sha256="5" * 64,
    )
    authority = tmp_path / "authority"
    contract_sha = write_blob(authority, canonical(contract))
    access = AccessScopeManifest(
        schema_version=1,
        run_id="DEV-001",
        status="FROZEN_BEFORE_TARGET_READ",
        contract_sha256=contract_sha,
        universe="csi300",
        symbols=tuple(member.symbol for member in members),
        membership_sha256=contract.corrected_membership_sha256,
        raw_dependency_span=contract.raw_dependency_span,
        signal_spans=(contract.train, contract.validation),
        alpha158_expression_sha256=contract.alpha158.expression_sha256,
        raw_fields=contract.alpha158.raw_dependencies,
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
        dataset_config_sha256=contract.dataset_config_sha256,
        use_config_sha256=contract.use_config_sha256,
        model_config_sha256=contract.model_config_sha256,
        archive_sha256=contract.archive_sha256,
        release_manifest_sha256=contract.release_manifest_sha256,
        extracted_tree_sha256=contract.extracted_tree_sha256,
        import_report_sha256=contract.import_report_sha256,
        factor_semantics_report_sha256=contract.factor_semantics_report_sha256,
        source_member_file_sha256=contract.source_member_file_sha256,
        member_correction_report_sha256=contract.member_correction_report_sha256,
        corrected_membership_sha256=contract.corrected_membership_sha256,
        calendar_sha256=contract.calendar_sha256,
        alpha158_expression_sha256=contract.alpha158.expression_sha256,
        universe="csi300",
        formal_qualification="BLOCKED_DATA",
        sealed_test="NOT_STARTED",
    )
    evidence_sha = write_blob(authority, canonical(evidence))
    provider = tmp_path / "provider"
    (provider / "calendars").mkdir(parents=True)
    (provider / "instruments").mkdir()
    (provider / "calendars/day.txt").write_text("fixture")
    (provider / "instruments/csi300.txt").write_text("fixture")
    return (
        authority,
        provider,
        tmp_path / "views",
        tmp_path / "results",
        members,
        contract_sha,
        evidence_sha,
    )


def test_staged_real_flow_withholds_targets_and_rebuilds_both_models(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    authority, provider, views, results, members, contract_sha, evidence_sha = _fixture(tmp_path)
    calls: list[tuple[tuple[str, ...], date, date]] = []

    def fake_reader(
        provider_uri: Path,
        scoped_members: tuple[Member, ...],
        fields: tuple[str, ...],
        names: tuple[str, ...],
        span: tuple[date, date],
    ) -> pd.DataFrame:
        symbols = tuple(sorted({member.symbol for member in scoped_members}))
        assert provider_uri == provider and "csi500" not in symbols
        calls.append((names, span[0], span[1]))
        days = tuple(pd.bdate_range(span[0], span[1]))
        index = pd.MultiIndex.from_product((symbols, days), names=["instrument", "datetime"])
        if names == (LABEL_COLUMN,):
            values = [
                0.002 * symbols.index(symbol) + 0.0001 * (day.day % 7) for symbol, day in index
            ]
            return pd.DataFrame({LABEL_COLUMN: values}, index=index)
        data = {
            name: [
                0.01 * (column + 1) + 0.001 * symbols.index(symbol) + 0.00001 * day.dayofyear
                for symbol, day in index
            ]
            for column, name in enumerate(names)
        }
        return pd.DataFrame(data, index=index)

    monkeypatch.setattr(view_module, "_read_qlib", fake_reader)
    view_sha, pin_sha = export_prediction_inputs(
        authority=authority,
        contract_sha256=contract_sha,
        evidence_sha256=evidence_sha,
        members=members,
        provider_uri=provider,
        view_root=views,
    )
    assert all(not (names == (LABEL_COLUMN,) and start.year == 2020) for names, start, _ in calls)
    runner = StagedRealRunner(
        authority=authority,
        view_root=views,
        result_root=results,
        contract_sha256=contract_sha,
        evidence_sha256=evidence_sha,
        view_pin_sha256=pin_sha,
    )
    receipts = (runner.freeze_predictions("linear"), runner.freeze_predictions("lightgbm"))
    with pytest.raises(ValueError, match="two distinct"):
        export_validation_targets(
            authority=authority,
            view_root=views,
            contract_sha256=contract_sha,
            evidence_sha256=evidence_sha,
            view_pin_sha256=pin_sha,
            provider_uri=provider,
            members=members,
            prediction_receipts=(receipts[0].sha256, receipts[0].sha256),
            result_root=results,
        )
    forged_payload = json.loads(read_blob(authority / "prediction_receipts", receipts[1].sha256))
    forged_payload["request"]["model"]["params"]["n_estimators"] = 201
    forged_payload["run_sha256"] = digest(forged_payload["request"])
    forged_receipt = write_blob(authority / "prediction_receipts", canonical(forged_payload))
    calls_before_forgery = len(calls)
    with pytest.raises(ValueError, match="does not bind"):
        export_validation_targets(
            authority=authority,
            view_root=views,
            contract_sha256=contract_sha,
            evidence_sha256=evidence_sha,
            view_pin_sha256=pin_sha,
            provider_uri=provider,
            members=members,
            prediction_receipts=(receipts[0].sha256, forged_receipt),
            result_root=results,
        )
    assert len(calls) == calls_before_forgery
    target_sha = export_validation_targets(
        authority=authority,
        view_root=views,
        contract_sha256=contract_sha,
        evidence_sha256=evidence_sha,
        view_pin_sha256=pin_sha,
        provider_uri=provider,
        members=members,
        prediction_receipts=(receipts[0].sha256, receipts[1].sha256),
        result_root=results,
    )
    assert any(names == (LABEL_COLUMN,) and start.year == 2020 for names, start, _ in calls)
    completed = [runner.evaluate(receipt.sha256, target_sha) for receipt in receipts]
    assert view_sha and {item.model for item in completed} == {"linear", "lightgbm"}
    assert all(item.status == "DEV_REAL_RUN_COMPLETED" for item in completed)
    assert all(item.prediction_rows == item.evaluated_rows > 0 for item in completed)
    assert all(item.mse is not None and np.isfinite(item.mse) for item in completed)


def test_mini_qlib_reader_requests_only_member_signal_spans(tmp_path: Path) -> None:
    provider = tmp_path / "qlib"
    (provider / "calendars").mkdir(parents=True)
    feature_root = provider / "features/sh600001"
    feature_root.mkdir(parents=True)
    (provider / "calendars/day.txt").write_text(
        "2020-01-02\n2020-01-03\n2020-01-06\n", encoding="utf-8"
    )
    np.asarray([0.0, 10.0, 999.0, 12.0], dtype="<f4").tofile(feature_root / "close.day.bin")
    members = (
        Member(symbol="sh600001", start=date(2020, 1, 2), end=date(2020, 1, 2)),
        Member(symbol="sh600001", start=date(2020, 1, 6), end=date(2020, 1, 6)),
    )
    frame = _read_qlib(
        provider,
        members,
        ("$close",),
        ("CLOSE",),
        (date(2020, 1, 2), date(2020, 1, 6)),
    )
    assert list(frame.index.get_level_values("datetime").date) == [
        date(2020, 1, 2),
        date(2020, 1, 6),
    ]
    assert frame["CLOSE"].tolist() == [10.0, 12.0]
