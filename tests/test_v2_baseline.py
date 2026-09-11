"""Tests for V2 frozen model baseline and sealed-run gates."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

import quant_stack_v2.baseline as baseline_module
from quant_stack_v2.baseline import (
    BaselineGateError,
    create_baseline_precommit,
    run_sealed_baseline_once,
)


def _precommit(tmp_path: Path):
    return create_baseline_precommit(
        tmp_path / "artifacts/v2",
        dataset_snapshot_sha256="a" * 64,
        pit_universe_sha256="b" * 64,
        code_commit="c" * 40,
        config_sha256="d" * 64,
    )[1]


def test_precommit_is_deterministic_and_freezes_twenty_seeds(tmp_path: Path) -> None:
    first = _precommit(tmp_path)
    second = _precommit(tmp_path)
    assert first.identity_sha256 == second.identity_sha256
    assert first.seeds == tuple(range(20))


def test_sealed_run_rejects_research_user_and_missing_marker(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    precommit = _precommit(tmp_path)
    monkeypatch.setattr(
        baseline_module.pwd, "getpwuid", lambda _: SimpleNamespace(pw_name="quant-research")
    )
    with pytest.raises(BaselineGateError, match="quant-eval"):
        run_sealed_baseline_once(
            precommit,
            model="linear",
            track="qlib_compat",
            seed=0,
        )
    monkeypatch.setattr(
        baseline_module.pwd, "getpwuid", lambda _: SimpleNamespace(pw_name="quant-eval")
    )
    monkeypatch.setattr(baseline_module, "_sealed_root_ready", lambda: False)
    with pytest.raises(BaselineGateError, match="not securely"):
        run_sealed_baseline_once(
            precommit,
            model="linear",
            track="qlib_compat",
            seed=0,
        )


def test_sealed_run_refuses_callback_free_execution_until_fixed_runner_exists(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    precommit = _precommit(tmp_path)
    monkeypatch.setattr(baseline_module, "SEALED_ROOT", tmp_path / "sealed_holdout")
    monkeypatch.setattr(baseline_module, "RESULT_ROOT", tmp_path / "results")
    monkeypatch.setattr(
        baseline_module.pwd, "getpwuid", lambda _: SimpleNamespace(pw_name="quant-eval")
    )
    monkeypatch.setattr(baseline_module, "_sealed_root_ready", lambda: True)
    with pytest.raises(BaselineGateError, match="fixed runner"):
        run_sealed_baseline_once(
            precommit,
            model="linear",
            track="qlib_compat",
            seed=0,
        )


def test_sealed_run_refuses_unreviewed_execution_even_for_evaluator_user(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    precommit = _precommit(tmp_path)
    monkeypatch.setattr(baseline_module, "SEALED_ROOT", tmp_path / "sealed_holdout")
    monkeypatch.setattr(baseline_module, "RESULT_ROOT", tmp_path / "results")
    monkeypatch.setattr(
        baseline_module.pwd, "getpwuid", lambda _: SimpleNamespace(pw_name="quant-eval")
    )
    monkeypatch.setattr(baseline_module, "_sealed_root_ready", lambda: True)
    with pytest.raises(BaselineGateError, match="fixed runner"):
        run_sealed_baseline_once(
            precommit,
            model="linear",
            track="qlib_compat",
            seed=0,
        )


def _metrics(**optional: float) -> dict[str, float]:
    return {
        "cagr": 0.1,
        "annualized_volatility": 0.2,
        "sharpe_ratio": 0.5,
        "maximum_drawdown": -0.1,
        "turnover": 1.0,
        "trade_count": 10.0,
        "total_transaction_costs": 5.0,
        "benchmark_cagr": 0.05,
        "benchmark_sharpe_ratio": 0.2,
        **optional,
    }
