"""Offline archive tests for the EXQ Tencent independent raw provider."""

from datetime import date
from pathlib import Path

import pandas as pd

from quant_stack_v2.tencent_provider import capture_history_batch


def test_capture_history_archives_unadjusted_tencent_span(tmp_path: Path) -> None:
    """The adapter retains a bounded raw response and request receipt."""
    frame = pd.DataFrame(
        [
            {
                "date": "2020-01-02",
                "open": 1,
                "close": 2,
                "high": 3,
                "low": 1,
                "volume": 4,
                "amount": 5,
            },
            {
                "date": "2020-01-03",
                "open": 2,
                "close": 3,
                "high": 4,
                "low": 2,
                "volume": 5,
                "amount": 6,
            },
        ]
    )
    manifests, failures = capture_history_batch(
        tmp_path,
        requests=(("sz000001", date(2020, 1, 2), date(2020, 1, 3)),),
        allow_network=True,
        query=lambda *_: frame,
    )
    assert not failures
    assert manifests[0].row_count == 2
    assert (tmp_path / "tencent_finance" / manifests[0].raw_sha256 / "response.csv").is_file()
