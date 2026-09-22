"""Deterministic bounded-statistics tests."""

import numpy as np

from quant_stack_v3.upgrade_statistics import _block_bootstrap_means, _holm


def test_shared_block_bootstrap_is_deterministic() -> None:
    values = np.column_stack([np.arange(30, dtype=float), np.arange(30, dtype=float) * 2])
    first = _block_bootstrap_means(values, 20, 5, 20260922)
    second = _block_bootstrap_means(values, 20, 5, 20260922)
    assert np.array_equal(first, second)
    assert np.array_equal(first[:, 1], first[:, 0] * 2)


def test_holm_adjustment_is_monotone_and_bounded() -> None:
    adjusted = _holm({"a": 0.01, "b": 0.03, "c": 0.2})
    assert 0 <= adjusted["a"] <= adjusted["b"] <= adjusted["c"] <= 1
    assert adjusted == {"a": 0.03, "b": 0.06, "c": 0.2}
