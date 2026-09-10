from datetime import date
from pathlib import Path

from quant_stack.experiment_registry import register_experiment


def test_registry_record_is_content_addressed_and_idempotent(tmp_path: Path) -> None:
    args = {
        "experiment_id": "etf_walk_forward_v1",
        "run_kind": "BASE_COST",
        "git_commit": "abc123",
        "data_snapshot_id": "snapshot123",
        "config_hashes": {"cost": "costhash", "strategy": "strategyhash"},
        "random_seed": 0,
        "payload": {"fold": 1},
    }
    first_id, first_path = register_experiment(tmp_path, **args)
    second_id, second_path = register_experiment(tmp_path, **args)
    assert first_id == second_id
    assert first_path == second_path
    assert first_path.parent.name == first_id


def test_registry_retains_distinct_preregistered_configurations(tmp_path: Path) -> None:
    common = {
        "experiment_id": "etf_walk_forward_v1",
        "git_commit": "abc123",
        "data_snapshot_id": "snapshot123",
        "config_hashes": {"cost": "costhash"},
        "random_seed": 0,
    }
    first_id, _ = register_experiment(tmp_path, run_kind="BASE_COST", payload={"fold": 1}, **common)
    second_id, _ = register_experiment(
        tmp_path, run_kind="DOUBLE_COST", payload={"fold": 1}, **common
    )
    assert first_id != second_id


def test_registry_serializes_frozen_date_fields_deterministically(tmp_path: Path) -> None:
    args = {
        "experiment_id": "etf_walk_forward_v2",
        "run_kind": "FOLD",
        "git_commit": "abc123",
        "data_snapshot_id": "snapshot123",
        "config_hashes": {"config": "hash"},
        "random_seed": 0,
        "payload": {"test_end": date(2026, 9, 9)},
    }

    first_id, _ = register_experiment(tmp_path, **args)
    second_id, _ = register_experiment(tmp_path, **args)

    assert first_id == second_id
