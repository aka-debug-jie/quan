"""Causal eligibility and fitted-preprocessor regressions on independent synthetic views."""

import json
from pathlib import Path
from typing import Any

import numpy as np
import pytest
from v2_dev_runner_smoke import _fixture, forbid_network  # noqa: F401

from quant_stack_v2.dev_baseline_runner import DevBaselineRunner
from quant_stack_v2.dev_contract import (
    UsePins,
    attest_synthetic,
    canonical,
    read_blob,
    tree_identity,
    write_blob,
)


def _reapprove(
    tmp_path: Path,
    authority: Path,
    views: Path,
    pins: UsePins,
    *,
    missing_future: bool = False,
    validation_shift: float = 0,
) -> UsePins:
    from quant_stack_v2.dev_view import export_view

    contract = json.loads(read_blob(authority, pins.contract_sha256))
    source_root = tmp_path / "source"
    source = json.loads(read_blob(source_root, contract["source_sha256"]))
    for row in source["rows"]:
        if missing_future and row["session"] > contract["valid"]["end"]:
            row["values"]["close"] = None
        if contract["valid"]["start"] <= row["session"] <= contract["valid"]["end"]:
            row["values"]["signal"] += validation_shift
    if missing_future:
        for member in source["members"]:
            member["end"] = contract["valid"]["end"]
    source_sha = write_blob(source_root, canonical(source))
    contract.update(
        source_sha256=source_sha, snapshot_sha256=source_sha, tree_sha256=tree_identity(source_sha)
    )
    csha = write_blob(authority, canonical(contract))
    esha = attest_synthetic(source_root, authority, csha)
    view_sha = export_view(source_root, authority, views, UsePins(csha, esha))
    # This is a new test-operator approval, not an untrusted request changing its pins.
    return UsePins(csha, esha, view_sha)


def _predictions(root: Path, result: Any) -> list[float]:
    manifest = json.loads(read_blob(root / "manifests", result.manifest_sha256))
    data = json.loads(read_blob(root / "predictions", manifest["artifacts"]["predictions_sha256"]))
    return [r["prediction"] for r in data["rows"]]


@pytest.mark.parametrize("model", ["linear", "lightgbm"])
def test_future_missing_prices_and_membership_do_not_remove_T_predictions(
    tmp_path: Path, model: str
) -> None:
    authority, views, results, pins, vsha = _fixture(tmp_path)
    original = DevBaselineRunner(
        authority=authority, view_root=views, result_root=results, pins=pins, view_sha256=vsha
    ).run(model)
    changed = _reapprove(tmp_path, authority, views, pins, missing_future=True)
    assert changed.view_sha256 is not None
    missing = DevBaselineRunner(
        authority=authority,
        view_root=views,
        result_root=results,
        pins=changed,
        view_sha256=changed.view_sha256,
    ).run(model)
    assert original.prediction_rows == missing.prediction_rows == 6
    np.testing.assert_array_equal(_predictions(results, original), _predictions(results, missing))
    assert missing.evaluated_rows == 0 and missing.mse is None and missing.ic is None


def test_validation_outliers_do_not_fit_preprocessing(tmp_path: Path) -> None:
    authority, views, results, pins, vsha = _fixture(tmp_path)
    first = DevBaselineRunner(
        authority=authority, view_root=views, result_root=results, pins=pins, view_sha256=vsha
    )
    a = first.run("linear")
    model_a = first.load_model(a)
    changed = _reapprove(tmp_path, authority, views, pins, validation_shift=1_000_000)
    assert changed.view_sha256 is not None
    second = DevBaselineRunner(
        authority=authority,
        view_root=views,
        result_root=results,
        pins=changed,
        view_sha256=changed.view_sha256,
    )
    b = second.run("linear")
    model_b = second.load_model(b)
    np.testing.assert_array_equal(
        model_a.named_steps["standardize"].mean_, model_b.named_steps["standardize"].mean_
    )
    np.testing.assert_array_equal(
        model_a.named_steps["model"].coef_, model_b.named_steps["model"].coef_
    )


def test_completed_run_rechecks_view_bytes_before_reuse(tmp_path: Path) -> None:
    authority, views, results, pins, vsha = _fixture(tmp_path)
    runner = DevBaselineRunner(
        authority=authority, view_root=views, result_root=results, pins=pins, view_sha256=vsha
    )
    runner.run("linear")
    manifest = json.loads(read_blob(views, vsha))
    path = views / (manifest["data_sha256"] + ".json")
    path.write_bytes(path.read_bytes() + b" ")
    with pytest.raises(ValueError, match="SHA-256"):
        runner.run("linear")


@pytest.mark.parametrize("case", ["missing", "wrong_target"])
def test_model_load_requires_correct_completion(tmp_path: Path, case: str) -> None:
    authority, views, results, pins, vsha = _fixture(tmp_path)
    runner = DevBaselineRunner(
        authority=authority, view_root=views, result_root=results, pins=pins, view_sha256=vsha
    )
    result = runner.run("linear")
    completion = results / "completions" / (result.run_sha256 + ".json")
    if case == "missing":
        completion.unlink()
    else:
        completion.write_bytes(
            canonical(
                {"schema_version": 1, "run_sha256": result.run_sha256, "manifest_sha256": "0" * 64}
            )
        )
    with pytest.raises(ValueError, match="completion"):
        runner.load_model(result)


def test_completion_failure_does_not_make_manifest_loadable(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import quant_stack_v2.dev_baseline_runner as module
    from quant_stack_v2.dev_contract import digest
    from quant_stack_v2.dev_view import load_view

    authority, views, results, pins, vsha = _fixture(tmp_path)
    runner = DevBaselineRunner(
        authority=authority, view_root=views, result_root=results, pins=pins, view_sha256=vsha
    )

    def failure(*args: object) -> None:
        raise OSError("completion publication interrupted")

    monkeypatch.setattr(module, "_complete_run", failure)
    with pytest.raises(OSError, match="completion"):
        runner.run("linear")
    manifest = next((results / "manifests").glob("*.json"))
    view = load_view(authority, views, pins, vsha)
    request = module._request(view, module._model_spec(view, "linear"))
    with pytest.raises(ValueError, match="completion"):
        module._load_result(results, manifest.stem, request, digest(request))


def test_zero_cannot_replace_undefined_metrics(tmp_path: Path) -> None:
    import quant_stack_v2.dev_baseline_runner as module
    from quant_stack_v2.dev_view import load_view

    authority, views, results, pins, _ = _fixture(tmp_path)
    changed = _reapprove(tmp_path, authority, views, pins, missing_future=True)
    assert changed.view_sha256 is not None
    runner = DevBaselineRunner(
        authority=authority,
        view_root=views,
        result_root=results,
        pins=changed,
        view_sha256=changed.view_sha256,
    )
    result = runner.run("linear")
    manifest = json.loads(read_blob(results / "manifests", result.manifest_sha256))
    payload = json.loads(read_blob(results / "results", manifest["artifacts"]["result_sha256"]))
    payload["metrics"] = {"mse": 0, "ic": 0}
    manifest["artifacts"]["result_sha256"] = write_blob(results / "results", canonical(payload))
    forged = write_blob(results / "manifests", canonical(manifest))
    view = load_view(authority, views, changed, changed.view_sha256)
    request = module._request(view, module._model_spec(view, "linear"))
    with pytest.raises(ValueError, match="undefined metrics"):
        module._load_result(results, forged, request, result.run_sha256)
