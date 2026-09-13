"""Explicit synthetic E2E smoke for the independent V2 dev runner."""

from __future__ import annotations

import json
from datetime import date, timedelta
from pathlib import Path
from typing import Any

import numpy as np
import pytest

import quant_stack_v2.dev_baseline_runner as runner_module
from quant_stack_v2.dev_baseline_runner import DevBaselineError, DevBaselineRunner
from quant_stack_v2.dev_contract import (
    DevContract,
    FeatureSpec,
    LabelSpec,
    Member,
    ModelSpec,
    Row,
    SourcePacket,
    Span,
    UsePins,
    attest_synthetic,
    canonical,
    tree_identity,
    write_blob,
)
from quant_stack_v2.dev_view import export_view, load_view


@pytest.fixture(autouse=True)
def forbid_network(monkeypatch: pytest.MonkeyPatch) -> None:
    """The dedicated runner smoke cannot use network or DNS."""

    def denied(*args: Any, **kwargs: Any) -> None:
        raise AssertionError("V2 dev runner smoke must not access the network")

    monkeypatch.setattr("socket.socket.connect", denied)
    monkeypatch.setattr("socket.socket.connect_ex", denied)
    monkeypatch.setattr("socket.create_connection", denied)
    monkeypatch.setattr("socket.getaddrinfo", denied)


def _fixture(tmp_path: Path) -> tuple[Path, Path, Path, UsePins, str]:
    sessions = tuple(date(2001, 1, 1) + timedelta(days=offset) for offset in range(12))
    symbols = ("SYNTH_A", "SYNTH_B", "SYNTH_C")
    rows: list[Row] = []
    for symbol_index, symbol in enumerate(symbols):
        for session_index, session in enumerate(sessions):
            close: float | None = 100.0 + 7.0 * symbol_index + session_index
            if symbol == "SYNTH_C" and session_index in {6, 11}:
                close = None  # one missing mature train label and one future valid label
            rows.append(
                Row(
                    symbol=symbol,
                    session=session,
                    values={
                        "close": close,
                        "signal": float(3 * symbol_index - 2 * session_index),
                    },
                )
            )
    source = SourcePacket(
        schema_version=1,
        data_kind="SYNTHETIC",
        universe="csi300",
        provider_id="SyntheticFixture",
        price_semantics="SYNTHETIC_POSITIVE_LEVELS",
        sessions=sessions,
        fields=("close", "signal"),
        members=tuple(
            Member(symbol=symbol, start=sessions[0], end=sessions[-1]) for symbol in symbols
        ),
        rows=tuple(rows),
    )
    source_root = tmp_path / "source"
    source_sha256 = write_blob(source_root, canonical(source))
    contract = DevContract(
        schema_version=1,
        usage="LIMITED_DEV_RESEARCH",
        run_kind="DEV_SMOKE",
        data_kind="SYNTHETIC",
        universe="csi300",
        formal_qualification="BLOCKED_DATA",
        sealed_test="NOT_STARTED",
        snapshot_sha256=source_sha256,
        tree_sha256=tree_identity(source_sha256),
        source_sha256=source_sha256,
        price_semantics="SYNTHETIC_POSITIVE_LEVELS",
        symbols=symbols,
        fields=("close", "signal"),
        sessions=sessions,
        source=Span(start=sessions[0], end=sessions[-1]),
        train=Span(start=sessions[2], end=sessions[4]),
        valid=Span(start=sessions[8], end=sessions[9]),
        warmup_sessions=1,
        train_label_end=sessions[6],
        valid_label_end=sessions[11],
        embargo_sessions=1,
        features=(
            FeatureSpec(name="close_now", field="close", lag=0),
            FeatureSpec(name="signal_lag1", field="signal", lag=1),
        ),
        label=LabelSpec(kind="forward_ratio", field="close", start_offset=1, end_offset=2),
        preprocessing="train_standardize_complete_cases",
        models=(
            ModelSpec(kind="linear", seed=1701, params={"fit_intercept": True}),
            ModelSpec(
                kind="lightgbm",
                seed=1701,
                params={
                    "n_estimators": 24,
                    "num_leaves": 7,
                    "learning_rate": 0.05,
                    "min_child_samples": 2,
                    "max_depth": 3,
                },
            ),
        ),
    )
    authority = tmp_path / "authority"
    contract_sha256 = write_blob(authority, canonical(contract))
    evidence_sha256 = attest_synthetic(source_root, authority, contract_sha256)
    export_pins = UsePins(contract_sha256, evidence_sha256)
    view_root = tmp_path / "view"
    view_sha256 = export_view(source_root, authority, view_root, export_pins)
    pins = UsePins(contract_sha256, evidence_sha256, view_sha256)
    return authority, view_root, tmp_path / "runner", pins, view_sha256


@pytest.mark.parametrize("model", ["linear", "lightgbm"])
def test_synthetic_runner_roundtrip_missing_labels_and_idempotence(
    tmp_path: Path, model: str
) -> None:
    authority, view_root, result_root, pins, view_sha256 = _fixture(tmp_path)
    runner = DevBaselineRunner(
        authority=authority,
        view_root=view_root,
        result_root=result_root,
        pins=pins,
        view_sha256=view_sha256,
    )
    first = runner.run(model)
    second = runner.run(model)

    assert first == second
    assert first.training_rows == 8
    assert first.prediction_rows == 6  # missing future labels do not remove predictions
    assert first.evaluated_rows == 5
    assert first.mse is not None and np.isfinite(first.mse)
    assert first.ic is None or np.isfinite(first.ic)
    assert first.status == "DEV_SMOKE_SYNTHETIC_COMPLETED"

    manifest = json.loads((result_root / "manifests" / f"{first.manifest_sha256}.json").read_text())
    assert manifest["use"] == {
        "contract_sha256": pins.contract_sha256,
        "evidence_sha256": pins.evidence_sha256,
    }
    assert manifest["view_sha256"] == view_sha256
    assert set(manifest) >= {
        "model_identity",
        "config_sha256",
        "code_sha256",
        "artifacts",
    }
    result_sha256 = manifest["artifacts"]["result_sha256"]
    result = json.loads((result_root / "results" / f"{result_sha256}.json").read_text())
    assert set(result["metrics"]) == {"mse", "ic"}

    view = load_view(authority, view_root, pins, view_sha256)
    samples = runner_module._assemble(view)
    restored = runner.load_model(first)
    roundtrip = np.asarray(restored.predict(samples.valid_x), dtype=float)
    predictions_sha256 = manifest["artifacts"]["predictions_sha256"]
    saved = json.loads((result_root / "predictions" / f"{predictions_sha256}.json").read_text())
    np.testing.assert_array_equal(roundtrip, [row["prediction"] for row in saved["rows"]])
    scaler = restored.named_steps["standardize"]  # type: ignore[attr-defined]
    np.testing.assert_allclose(scaler.mean_, samples.train_x.mean(axis=0))


def test_same_dev_slot_rejects_code_drift(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    authority, view_root, result_root, pins, view_sha256 = _fixture(tmp_path)
    runner = DevBaselineRunner(
        authority=authority,
        view_root=view_root,
        result_root=result_root,
        pins=pins,
        view_sha256=view_sha256,
    )
    runner.run("linear")
    monkeypatch.setattr(runner_module, "_code_sha256", lambda: "f" * 64)
    with pytest.raises(DevBaselineError, match="drift"):
        runner.run("linear")


def test_same_request_rejects_prediction_reproducibility_drift(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    authority, view_root, result_root, pins, view_sha256 = _fixture(tmp_path)
    runner = DevBaselineRunner(
        authority=authority,
        view_root=view_root,
        result_root=result_root,
        pins=pins,
        view_sha256=view_sha256,
    )
    completed = runner.run("linear")
    pointer = result_root / "completions" / f"{completed.run_sha256}.json"
    original_pointer = pointer.read_bytes()
    original_vector = runner_module._vector

    def shifted(value: object) -> np.ndarray[Any, np.dtype[np.float64]]:
        return original_vector(value) + 0.25

    monkeypatch.setattr(runner_module, "_vector", shifted)
    with pytest.raises(DevBaselineError, match="reproducibility drift"):
        runner.run("linear")
    assert pointer.read_bytes() == original_pointer
    assert (result_root / "manifests" / f"{completed.manifest_sha256}.json").is_file()
    failures = list((result_root / "failures" / completed.run_sha256).glob("*.json"))
    assert len(failures) == 1
    assert "reproducibility drift" in json.loads(failures[0].read_text())["message"]


def test_interruption_is_retained_without_complete_manifest(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    authority, view_root, result_root, pins, view_sha256 = _fixture(tmp_path)
    runner = DevBaselineRunner(
        authority=authority,
        view_root=view_root,
        result_root=result_root,
        pins=pins,
        view_sha256=view_sha256,
    )

    completed = runner.run("linear")
    manifest_path = result_root / "manifests" / f"{completed.manifest_sha256}.json"
    original_manifest = manifest_path.read_bytes()

    def interrupt(specification: ModelSpec) -> None:
        raise KeyboardInterrupt("synthetic interruption")

    with monkeypatch.context() as context:
        context.setattr(runner_module, "_make_estimator", interrupt)
        with pytest.raises(KeyboardInterrupt, match="synthetic interruption"):
            runner.run("linear")

    failures = list((result_root / "failures").glob("*/*.json"))
    assert len(failures) == 1
    assert json.loads(failures[0].read_text())["status"] == "INTERRUPTED"
    assert manifest_path.read_bytes() == original_manifest


def test_partial_artifacts_never_publish_a_complete_manifest(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    authority, view_root, result_root, pins, view_sha256 = _fixture(tmp_path)
    runner = DevBaselineRunner(
        authority=authority,
        view_root=view_root,
        result_root=result_root,
        pins=pins,
        view_sha256=view_sha256,
    )
    original = runner_module.write_blob

    def fail_prediction(root: Path, body: bytes, suffix: str = ".json") -> str:
        if root.name == "predictions":
            raise OSError("synthetic publication failure")
        return original(root, body, suffix)

    monkeypatch.setattr(runner_module, "write_blob", fail_prediction)
    with pytest.raises(OSError, match="publication failure"):
        runner.run("linear")
    assert not (result_root / "manifests").exists()
    failure = next((result_root / "failures").glob("*/*.json"))
    assert json.loads(failure.read_text())["status"] == "FAILED"


@pytest.mark.parametrize(
    ("case", "message"),
    [
        ("manifest_extra", "manifest schema"),
        ("manifest_status", "manifest run identity"),
        ("artifact_extra", "artifact schema"),
        ("combined_metric", "result schema"),
        ("result_model", "result identity"),
        ("count_relation", "sample bounds"),
        ("prediction_count", "prediction artifact"),
    ],
)
def test_loader_rejects_schema_identity_count_and_prediction_drift(
    tmp_path: Path, case: str, message: str
) -> None:
    authority, view_root, result_root, pins, view_sha256 = _fixture(tmp_path)
    runner = DevBaselineRunner(
        authority=authority,
        view_root=view_root,
        result_root=result_root,
        pins=pins,
        view_sha256=view_sha256,
    )
    completed = runner.run("linear")
    view = load_view(authority, view_root, pins, view_sha256)
    request = runner_module._request(view, runner_module._model_spec(view, "linear"))
    manifest = json.loads(
        (result_root / "manifests" / f"{completed.manifest_sha256}.json").read_text()
    )
    artifacts = manifest["artifacts"]
    result = json.loads(
        (result_root / "results" / f"{artifacts['result_sha256']}.json").read_text()
    )
    predictions = json.loads(
        (result_root / "predictions" / f"{artifacts['predictions_sha256']}.json").read_text()
    )

    if case == "manifest_extra":
        manifest["combined_score"] = 0
    elif case == "manifest_status":
        manifest["status"] = "QUALIFIED"
    elif case == "artifact_extra":
        artifacts["portfolio_sha256"] = "0" * 64
    elif case == "combined_metric":
        result["combined_score"] = 0
    elif case == "result_model":
        result["model"] = "lightgbm"
    elif case == "count_relation":
        result["evaluated_rows"] = result["prediction_rows"] + 1
    elif case == "prediction_count":
        predictions["rows"].pop()
    else:
        raise AssertionError("unknown mutation")

    if case in {"combined_metric", "result_model", "count_relation"}:
        artifacts["result_sha256"] = write_blob(result_root / "results", canonical(result))
    if case == "prediction_count":
        artifacts["predictions_sha256"] = write_blob(
            result_root / "predictions", canonical(predictions)
        )
    forged_manifest = write_blob(result_root / "manifests", canonical(manifest))
    with pytest.raises(DevBaselineError, match=message):
        runner_module._load_result(result_root, forged_manifest, request, completed.run_sha256)
