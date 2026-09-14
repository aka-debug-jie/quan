"""Offline AF-002 fixed-fold and redundancy tests."""

from __future__ import annotations

from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from quant_stack_v2.af001 import AlphaRegistry
from quant_stack_v2.af001 import load_registry as load_af001_registry
from quant_stack_v2.af002 import AF002Registry, evaluate_frames, load_registry
from quant_stack_v2.dev_real_staged_view import LABEL_COLUMN


def _registries() -> tuple[AF002Registry, AlphaRegistry]:
    root = Path(__file__).parents[1]
    return (
        load_registry(root / "configs/v2/alphas/af_002_walk_forward_v1.yaml"),
        load_af001_registry(root / "configs/v2/alphas/af_001_alpha_registry_v1.yaml"),
    )


def _frames(
    registry: AF002Registry, af001: AlphaRegistry
) -> tuple[pd.DataFrame, pd.DataFrame, dict[str, object]]:
    sessions = [date(year, 1, day) for year in range(2017, 2021) for day in range(1, 32)]
    symbols = ["sh600001", "sz000001", "sz000002"]
    rows = [(session, symbol) for session in sessions for symbol in symbols]
    features = pd.DataFrame(rows, columns=["session", "symbol"])
    alphas = af001.alphas
    for index, alpha in enumerate(alphas):
        features[alpha.source_feature] = np.asarray(
            [float(index + item % len(symbols)) for item in range(len(features))]
        )
    labels = features.loc[:, ["session", "symbol"]].copy()
    labels[LABEL_COLUMN] = np.tile(np.asarray([0.1, 0.2, 0.3]), len(sessions))
    candidate_ids = [item.alpha_id for item in alphas[:2]]
    statuses = [
        {
            "alpha_id": item.alpha_id,
            "status": (
                "CANDIDATE_PENDING_AF002"
                if item.alpha_id in candidate_ids
                else "REJECTED_NO_STABLE_SIGNAL"
            ),
        }
        for item in alphas
    ]
    return features, labels, {"alphas": statuses}


def test_af002_registry_has_fixed_folds_and_boundaries() -> None:
    registry, _ = _registries()
    assert [fold.fold_id for fold in registry.folds] == ["WF_2017", "WF_2018", "WF_2019", "WF_2020"]
    assert registry.redundancy.maximum_candidates == 8
    assert registry.exposure_diagnostics.industry == "NOT_AVAILABLE_IN_APPROVED_VIEW"


def test_af002_rejects_fold_date_drift(tmp_path: Path) -> None:
    root = Path(__file__).parents[1]
    source = root / "configs/v2/alphas/af_002_walk_forward_v1.yaml"
    body = source.read_text(encoding="utf-8").replace("start: 2017-01-01", "start: 2017-01-02")
    path = tmp_path / "drift.yaml"
    path.write_text(body, encoding="utf-8")
    with pytest.raises(ValueError, match="exactly the four fixed annual folds"):
        load_registry(path)


def test_fixed_evaluation_keeps_clusters_and_unavailable_exposures() -> None:
    registry, af001 = _registries()
    features, labels, result = _frames(registry, af001)
    output = evaluate_frames(registry, af001, result, features, labels)
    assert output["selected_count"] <= 8
    assert len(output["factors"]) == 16
    assert output["exposure_limitation"]["market_cap"] == "NOT_AVAILABLE_IN_APPROVED_VIEW"
    first = output["factors"][0]
    assert len(first["folds"]) == 4
    assert first["folds"][0]["industry_exposure"] == "NOT_AVAILABLE_IN_APPROVED_VIEW"
    carried = next(item for item in output["factors"] if not item["folds"])
    assert carried["stability"]["rejection_reasons"] == ["AF001_REJECTED_NO_STABLE_SIGNAL"]


def test_rejected_af001_rows_cannot_enter_af002() -> None:
    registry, af001 = _registries()
    features, labels, _ = _frames(registry, af001)
    result = {
        "alphas": [{"alpha_id": af001.alphas[0].alpha_id, "status": "REJECTED_NO_STABLE_SIGNAL"}]
    }
    try:
        evaluate_frames(registry, af001, result, features, labels)
    except ValueError as error:
        assert "no valid frozen candidate" in str(error)
    else:
        raise AssertionError("AF-002 accepted an AF-001 rejected factor")
