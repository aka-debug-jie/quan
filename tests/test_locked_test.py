import subprocess
from datetime import date
from pathlib import Path

import pytest

from quant_stack.issue009_runner import _claim_locked_attempt
from quant_stack.locked_test import (
    LockedAssetInput,
    LockedTestPrecommit,
    _hash_json,
    _require_clean_tracked_tree,
    persist_locked_test_precommit,
)


def _precommit() -> LockedTestPrecommit:
    return LockedTestPrecommit(
        precommit_id="a" * 64,
        version="1.0.0",
        status="LOCKED_TEST_PRECOMMIT",
        experiment_id="test",
        code_commit="commit",
        tracked_tree_sha256="b" * 64,
        data_snapshot_id="c" * 64,
        qualification_report_id="d" * 64,
        qualification_report_sha256="d" * 64,
        source_registry_sha256="e" * 64,
        source_registry_path="configs/data_qualification/d0_sources_v1.yaml",
        experiment_config_path="config.yaml",
        experiment_config_sha256="f" * 64,
        config_hashes={"config": "f" * 64},
        walk_forward_split_sha256="1" * 64,
        selection_period_end="2023-12-29",
        locked_test_start="2024-01-02",
        locked_test_end="2024-12-31",
        last_locked_signal_date="2024-11-29",
        random_seed=0,
        assets=(
            LockedAssetInput(
                symbol="ETF",
                exchange="SSE",
                raw_manifest_id="2" * 64,
                raw_normalized_sha256="3" * 64,
                causal_manifest_id="4" * 64,
                causal_output_sha256="5" * 64,
                ledger_sha256="6" * 64,
                reproduction_report_id="7" * 64,
            ),
        ),
    )


def test_precommit_persistence_is_immutable_and_idempotent(tmp_path: Path) -> None:
    path = tmp_path / "precommit.json"
    first = persist_locked_test_precommit(_precommit(), path)
    second = persist_locked_test_precommit(_precommit(), path)

    assert first == second
    assert '"status":"LOCKED_TEST_PRECOMMIT"' in path.read_text(encoding="utf-8")


def test_precommit_gate_rejects_a_dirty_tracked_tree(tmp_path: Path) -> None:
    subprocess.run(("git", "init", "-q"), cwd=tmp_path, check=True)
    tracked = tmp_path / "tracked.txt"
    tracked.write_text("frozen", encoding="utf-8")
    subprocess.run(("git", "add", "tracked.txt"), cwd=tmp_path, check=True)
    subprocess.run(
        (
            "git",
            "-c",
            "user.name=test",
            "-c",
            "user.email=test@example.invalid",
            "commit",
            "-qm",
            "freeze",
        ),
        cwd=tmp_path,
        check=True,
    )
    _require_clean_tracked_tree(tmp_path)
    executable = tmp_path / "untracked.py"
    executable.write_text("raise RuntimeError\n", encoding="utf-8")
    with pytest.raises(ValueError, match="research Git tree must be clean"):
        _require_clean_tracked_tree(tmp_path)
    executable.unlink()
    tracked.write_text("changed", encoding="utf-8")

    with pytest.raises(ValueError, match="research Git tree must be clean"):
        _require_clean_tracked_tree(tmp_path)


def test_locked_attempt_is_consumed_before_result_creation(tmp_path: Path) -> None:
    first = _claim_locked_attempt(tmp_path, _precommit())

    assert (first / "attempt.json").is_file()
    with pytest.raises(ValueError, match="already been attempted"):
        _claim_locked_attempt(tmp_path, _precommit())


def test_precommit_hash_serializes_frozen_dates_deterministically() -> None:
    assert _hash_json({"end": date(2026, 9, 9)}) == _hash_json({"end": "2026-09-09"})
