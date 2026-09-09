from datetime import date, timedelta
from pathlib import Path

import pytest

from quant_stack.walk_forward import (
    chronological_splits,
    load_preregistered_experiment,
    require_executable_experiment,
    verify_declared_config_hashes,
)


def test_walk_forward_never_trains_on_its_future_test_interval() -> None:
    dates = [date(2020, 1, 1) + timedelta(days=index) for index in range(10)]
    splits = chronological_splits(dates, 4, 2)
    assert len(splits) == 3
    assert all(split.train_end < split.test_start for split in splits)


def test_loads_only_frozen_preregistered_experiment() -> None:
    config = load_preregistered_experiment(Path("configs/experiments/etf_walk_forward_v1.yaml"))
    assert config["locked_test_start"] == date(2024, 1, 2)
    verify_declared_config_hashes(config, Path("."))
    with pytest.raises(ValueError, match="snapshot identity"):
        require_executable_experiment(config, "")


def test_experiment_rejects_changed_frozen_config(tmp_path: Path) -> None:
    config_path = tmp_path / "config.yaml"
    config_path.write_text("version: 1\n", encoding="utf-8")
    config = {
        "frozen_config_sha256": {
            "config.yaml": "09bfcc6a14b83e2192b8673677725c84883ee9cd0c70e45c9ec09daa8f2b2847"
        }
    }
    verify_declared_config_hashes(config, tmp_path)
    config_path.write_text("version: 2\n", encoding="utf-8")
    with pytest.raises(ValueError, match="hash mismatch"):
        verify_declared_config_hashes(config, tmp_path)
