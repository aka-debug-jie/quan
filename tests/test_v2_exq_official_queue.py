"""Offline scope-conservation tests for the EXQ official evidence queue."""

from pathlib import Path

from quant_stack_v2.exq_official_queue import build_queue


def test_queue_groups_only_exact_residual_keys() -> None:
    """Queue tasks retain all and only the supplied EXQ residual sessions."""
    root = Path(__file__).parents[1]
    queue = build_queue(
        {
            "lifecycle_and_suspension": {
                "free_residual_intersection": [
                    {"symbol": "sh600001", "expected_session": "2020-01-02"},
                    {"symbol": "sh600001", "expected_session": "2020-01-03"},
                    {"symbol": "sz000001", "expected_session": "2020-01-02"},
                ]
            }
        },
        root / "configs/v2/execution/exq_001_cn_stock_rules_v1.yaml",
    )
    assert queue["task_count"] == 2
    assert queue["session_count"] == 3
    assert queue["tasks"][0]["official_suspension_source"] == "SSE_STOP_RESUME_QUERY"
