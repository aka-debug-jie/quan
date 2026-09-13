"""Complete reduced queue regressions; no live data or network."""

from pathlib import Path

import pytest
from test_v2_szse_monthly import hashed

from quant_stack_v2.szse_evidence_queue import build_queue


def report() -> dict[str, object]:
    missing = [
        dict(symbol="sz000001", session=d, classification="UNEXPLAINED")
        for d in ("2015-01-05", "2015-01-07")
    ]
    return dict(
        scope="SZSE_MONTHLY_PLUS_ISSUER_NOTICES_RETROSPECTIVE",
        residual=missing,
        uncovered_sessions=2,
        gap_gate="BLOCKED_DATA",
        membership_gate="BLOCKED_DATA",
        results=[
            dict(
                task=dict(symbol="sz000001", start_session="2015-01-05", end_session="2015-01-07"),
                dates=[
                    dict(session="2015-01-05", classification="UNEXPLAINED"),
                    dict(session="2015-01-06", classification="OFFICIAL_SUSPENDED"),
                    dict(session="2015-01-07", classification="UNEXPLAINED"),
                ],
            )
        ],
    )


def test_queue_counts_only_residual_dates(tmp_path: Path) -> None:
    result = build_queue(hashed(tmp_path, report()))
    assert result["rows"] == [
        ["sz000001", "2015-01-05", "2015-01-07", "2015-01-05", "2015-01-07", 2]
    ]
    assert result["task_count"] == 1
    assert result["residual_sessions"] == 2
    assert result["gap_gate"] == result["membership_gate"] == "BLOCKED_DATA"


def test_tamper_and_accounting(tmp_path: Path) -> None:
    path = hashed(tmp_path, report())
    path.write_bytes(b"tamper")
    with pytest.raises(ValueError, match="SHA"):
        build_queue(path)
    with pytest.raises(ValueError, match="count"):
        build_queue(hashed(tmp_path, report() | {"uncovered_sessions": 3}))
    with pytest.raises(ValueError, match="differ"):
        build_queue(hashed(tmp_path, report() | {"results": []}))
