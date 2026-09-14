"""Offline AF-001 registry and diagnostic tests."""

from __future__ import annotations

from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from quant_stack_v2.af001 import AF001Error, AlphaRegistry, evaluate_frames, load_registry
from quant_stack_v2.dev_real_staged_view import LABEL_COLUMN


def _registry() -> AlphaRegistry:
    root = Path(__file__).parents[1]
    return load_registry(root / "configs/v2/alphas/af_001_alpha_registry_v1.yaml")


def _frames() -> tuple[pd.DataFrame, pd.DataFrame]:
    registry = _registry()
    sessions = [date(2020, 2, 7), date(2020, 2, 10)]
    symbols = ["sh600001", "sz000001", "sz000002"]
    rows = [(session, symbol) for session in sessions for symbol in symbols]
    features = pd.DataFrame(rows, columns=["session", "symbol"])
    for index, alpha in enumerate(registry.alphas):  # type: ignore[union-attr]
        features[alpha.source_feature] = np.asarray(
            [index + position + 1.0 for position in range(len(features))]
        )
    labels = features.loc[:, ["session", "symbol"]].copy()
    labels[LABEL_COLUMN] = np.asarray([0.1, 0.2, 0.3, 0.3, 0.2, 0.1])
    return features, labels


def test_registry_is_fixed_to_sixteen_direct_alpha158_transforms() -> None:
    from qlib.contrib.data.handler import Alpha158

    registry = _registry()
    assert len(registry.alphas) == 16
    assert len({alpha.alpha_id for alpha in registry.alphas}) == 16
    assert all(alpha.required_fields == (alpha.source_feature,) for alpha in registry.alphas)
    expressions, names = Alpha158.get_feature_config(object.__new__(Alpha158))
    resolved = dict(zip(names, expressions, strict=True))
    assert all(
        resolved[alpha.source_feature] == alpha.source_expression for alpha in registry.alphas
    )


def test_evaluation_keeps_all_preregistered_alphas_and_reports_coverage() -> None:
    registry = _registry()
    features, labels = _frames()
    result = evaluate_frames(
        registry,
        features,
        labels,
        member_signal_rows=8,
        feature_cells=8 * 158,
        missing_feature_cells=12,
        segments={"year_2020": (date(2020, 1, 1), date(2020, 12, 31))},
    )
    assert len(result["alphas"]) == 16
    assert result["coverage"]["member_grid_feature_coverage"] == 0.75  # type: ignore[index]
    assert result["coverage"]["aggregate_feature_cell_missing_rate"] == 12 / (8 * 158)  # type: ignore[index]
    first = result["alphas"][0]  # type: ignore[index]
    assert first["metrics"]["defined_days"] == 2  # type: ignore[index]
    assert first["status"] == "REJECTED_NO_STABLE_SIGNAL"


def test_missing_preregistered_feature_fails_closed() -> None:
    registry = _registry()
    features, labels = _frames()
    features = features.drop(columns=[registry.alphas[0].source_feature])
    with pytest.raises(AF001Error, match="lacks preregistered feature"):
        evaluate_frames(
            registry,
            features,
            labels,
            member_signal_rows=6,
            feature_cells=6 * 158,
            missing_feature_cells=0,
            segments={},
        )


def test_constant_cross_section_is_retained_with_undefined_daily_metrics() -> None:
    registry = _registry()
    features, labels = _frames()
    for alpha in registry.alphas:
        features[alpha.source_feature] = 1.0
    result = evaluate_frames(
        registry,
        features,
        labels,
        member_signal_rows=6,
        feature_cells=6 * 158,
        missing_feature_cells=0,
        segments={},
    )
    first = result["alphas"][0]  # type: ignore[index]
    assert first["metrics"]["daily_rank_ic"] is None  # type: ignore[index]
    assert first["metrics"]["undefined_reason"] == "INSUFFICIENT_OR_CONSTANT_DAILY_CROSS_SECTIONS"  # type: ignore[index]
