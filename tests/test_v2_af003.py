"""Offline AF-003 preregistration and chronological-fold tests."""

from __future__ import annotations

from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

import quant_stack_v2.af003 as af003
from quant_stack_v2.af003 import AF003Error, evaluate_frames, load_registry
from quant_stack_v2.dev_real_staged_view import LABEL_COLUMN


def _registry() -> object:
    root = Path(__file__).parents[1]
    return load_registry(root / "configs/v2/alphas/af_003_combination_v1.yaml")


def _frames(registry: object) -> tuple[pd.DataFrame, pd.DataFrame, dict[str, tuple[str, int]]]:
    sessions = [date(year, 1, day) for year in range(2015, 2021) for day in range(1, 32)]
    symbols = ["sh600001", "sz000001", "sz000002"]
    rows = [(session, symbol) for session in sessions for symbol in symbols]
    features = pd.DataFrame(rows, columns=["session", "symbol"])
    source: dict[str, tuple[str, int]] = {}
    for index, alpha in enumerate(registry.candidate_alpha_ids):
        field = f"F{index}"
        source[alpha] = (field, 1)
        features[field] = np.tile(np.asarray([1.0, 2.0, 3.0]), len(sessions)) + index
    labels = features.loc[:, ["session", "symbol"]].copy()
    labels[LABEL_COLUMN] = np.tile(np.asarray([0.1, 0.2, 0.3]), len(sessions))
    return features, labels, source


def test_registry_rejects_fold_drift(tmp_path: Path) -> None:
    root = Path(__file__).parents[1]
    source = root / "configs/v2/alphas/af_003_combination_v1.yaml"
    path = tmp_path / "drift.yaml"
    path.write_text(
        source.read_text(encoding="utf-8").replace("test_end: 2017-12-31", "test_end: 2017-12-30"),
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="fold or candidate preregistration"):
        load_registry(path)


def test_fixed_folds_keep_all_models_and_purge_two_sessions(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    registry = _registry()
    features, labels, source = _frames(registry)
    monkeypatch.setattr(
        af003,
        "_model_predictions",
        lambda _registry, _model, _train_x, _train_y, test_x, _test_y, _sessions: (
            test_x.iloc[:, 0].to_numpy(dtype=float),
            {str(column): 1 / len(test_x.columns) for column in test_x.columns},
            {"status": "FIXED_SEEDS", "seeds": [0, 1, 2]},
        ),
    )
    output = evaluate_frames(registry, features, labels, source)
    assert len(output["folds"]) == 4
    assert output["selected_simple_model"] in registry.simple_models
    assert output["selected_ml_challenger"] in {*registry.models, "NO_STABLE_ML_INCREMENT"}
    first = output["folds"][0]
    assert first["resolved_train_signal_end"] < "2016-12-31"
    assert set(first["models"]) == {
        "equal_weight_zscore",
        "train_rank_ic_weighted_zscore",
        "ridge",
        "elasticnet",
        "lightgbm",
        "xgboost",
    }
    assert "portfolio_returns" not in str(output)


def test_missing_source_feature_fails_closed() -> None:
    registry = _registry()
    features, labels, source = _frames(registry)
    features = features.drop(columns=[source[registry.candidate_alpha_ids[0]][0]])
    with pytest.raises(AF003Error, match="feature schema"):
        evaluate_frames(registry, features, labels, source)
