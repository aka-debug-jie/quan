"""Explicit V2 dependency-group smoke tests; only generated in-memory observations."""

from importlib import import_module
from importlib.metadata import version
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import numpy as np
import pandas as pd
import pytest


@pytest.fixture(autouse=True)
def forbid_network(monkeypatch: pytest.MonkeyPatch) -> None:
    """Fail immediately if a smoke test attempts a network connection."""

    def denied(*args: Any, **kwargs: Any) -> None:
        raise AssertionError("V2 synthetic smoke must not access the network")

    monkeypatch.setattr("socket.socket.connect", denied)
    monkeypatch.setattr("socket.socket.connect_ex", denied)
    monkeypatch.setattr("socket.create_connection", denied)
    monkeypatch.setattr("socket.getaddrinfo", denied)


@pytest.mark.parametrize(
    ("distribution", "expected"),
    [("pyqlib", "0.9.7"), ("lightgbm", "4.5.0"), ("xgboost", "2.1.4")],
)
def test_locked_v2_versions(distribution: str, expected: str) -> None:
    assert version(distribution) == expected
    module = import_module("qlib" if distribution == "pyqlib" else distribution)
    assert module.__version__ == expected


@pytest.mark.parametrize("kind", ["linear", "lightgbm"])
def test_qlib_synthetic_model_roundtrip(
    kind: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from qlib.contrib.model.gbdt import LGBModel
    from qlib.contrib.model.linear import LinearModel
    from qlib.data.dataset import DatasetH
    from qlib.data.dataset.handler import DataHandlerLP

    # This fixture has no relationship to a frozen market experiment or its seeds.
    rng = np.random.default_rng(1701)
    dates = pd.date_range("2000-01-01", periods=100)
    index = pd.MultiIndex.from_product(
        [dates, ["SYNTH_A", "SYNTH_B"]], names=["datetime", "instrument"]
    )
    x = rng.normal(size=(len(index), 3))
    y = 2.0 * x[:, 0] - 0.5 * x[:, 1] + 0.25 * x[:, 2]
    columns = pd.MultiIndex.from_tuples([("feature", f"x{i}") for i in range(3)] + [("label", "y")])
    frame = pd.DataFrame(np.column_stack([x, y]), index=index, columns=columns)
    dataset = DatasetH(
        handler=DataHandlerLP.from_df(frame),
        segments={
            "train": (dates[0], dates[59]),
            "valid": (dates[60], dates[79]),
            "test": (dates[80], dates[99]),
        },
    )
    metrics: list[dict[str, Any]] = []
    # Exercise real model fitting, without starting an MLflow experiment or recorder.
    monkeypatch.setattr(
        "qlib.contrib.model.gbdt.R", SimpleNamespace(log_metrics=lambda **kw: metrics.append(kw))
    )
    model = (
        LinearModel()
        if kind == "linear"
        else LGBModel(
            num_boost_round=60,
            early_stopping_rounds=10,
            num_threads=1,
            learning_rate=0.1,
            num_leaves=7,
            min_data_in_leaf=5,
            seed=1701,
            deterministic=True,
            force_col_wise=True,
        )
    )
    model.fit(dataset)
    prediction = model.predict(dataset)
    truth = frame.loc[pd.IndexSlice[dates[80] : dates[99], :], ("label", "y")]
    pd.testing.assert_index_equal(prediction.index, truth.index)
    assert len(prediction) == 40 and np.isfinite(prediction.to_numpy()).all()
    assert np.var(prediction.to_numpy()) > 0
    assert np.mean((prediction.to_numpy() - truth.to_numpy()) ** 2) < np.var(truth.to_numpy()) * 0.5
    if kind == "lightgbm":
        assert metrics and model.model.current_iteration() > 0
    path = tmp_path / f"synthetic-{kind}.pkl"
    model.to_pickle(path, dump_all=True)
    assert path.stat().st_size > 0
    restored = type(model).load(path)
    assert restored is not model
    pd.testing.assert_series_equal(prediction, restored.predict(dataset), check_exact=True)
