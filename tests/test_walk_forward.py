from datetime import date, timedelta
from pathlib import Path

from quant_stack.walk_forward import chronological_splits, load_preregistered_experiment


def test_walk_forward_never_trains_on_its_future_test_interval() -> None:
    dates = [date(2020, 1, 1) + timedelta(days=index) for index in range(10)]
    splits = chronological_splits(dates, 4, 2)
    assert len(splits) == 3
    assert all(split.train_end < split.test_start for split in splits)


def test_loads_only_frozen_preregistered_experiment() -> None:
    config = load_preregistered_experiment(Path("configs/experiments/etf_walk_forward_v1.yaml"))
    assert config["locked_test_start"] == date(2024, 1, 2)
