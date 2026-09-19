"""Offline archive tests for the EXQ AKShare independent raw provider."""

from datetime import date
from pathlib import Path

import pandas as pd

from quant_stack_v2.akshare_provider import capture_batch, capture_daily, capture_history_batch


def _frame(session: str) -> pd.DataFrame:
    return pd.DataFrame(
        [{"日期": session, "开盘": 1, "收盘": 2, "最高": 3, "最低": 1, "成交量": 4, "成交额": 5}]
    )


def test_capture_daily_archives_unadjusted_request_and_response(tmp_path: Path) -> None:
    """One exact day retains the source response and request metadata."""
    manifest = capture_daily(
        tmp_path,
        symbol="sz000001",
        session=date(2020, 1, 2),
        allow_network=True,
        query=lambda *_: _frame("2020-01-02"),
    )
    assert manifest.row_count == 1
    assert (tmp_path / "akshare_eastmoney" / manifest.raw_sha256 / "response.csv").is_file()


def test_capture_batch_archives_empty_response(tmp_path: Path) -> None:
    """An empty exact-day response remains evidence, rather than a fabricated halt."""
    manifests, failures = capture_batch(
        tmp_path,
        requests=(("sz000001", date(2020, 1, 2)), ("sz000002", date(2020, 1, 3))),
        allow_network=True,
        query=lambda symbol, *_: _frame("2020-01-02") if symbol == "000001" else pd.DataFrame(),
    )
    assert len(manifests) == 2
    assert not failures
    assert next(item for item in manifests if item.symbol == "sz000002").row_count == 0


def test_capture_history_batch_archives_only_requested_span(tmp_path: Path) -> None:
    """A bounded history request retains normal trading rows without widening its range."""
    frame = pd.concat([_frame("2020-01-02"), _frame("2020-01-03")], ignore_index=True)
    manifests, failures = capture_history_batch(
        tmp_path,
        requests=(("sz000001", date(2020, 1, 2), date(2020, 1, 3)),),
        allow_network=True,
        query=lambda *_: frame,
    )
    assert not failures
    assert manifests[0].row_count == 2
    assert manifests[0].start_date == "2020-01-02"
    assert manifests[0].end_date == "2020-01-03"
