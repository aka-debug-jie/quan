from datetime import date, timedelta

from quant_stack.walk_forward import chronological_splits


def test_walk_forward_never_trains_on_its_future_test_interval() -> None:
    dates = [date(2020, 1, 1) + timedelta(days=index) for index in range(10)]
    splits = chronological_splits(dates, 4, 2)
    assert len(splits) == 3
    assert all(split.train_end < split.test_start for split in splits)
