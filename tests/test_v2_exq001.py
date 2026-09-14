"""Offline EXQ-001 scope and frozen-residual intersection tests."""

from datetime import date
from pathlib import Path

import pytest

from quant_stack_v2.dev_contract import Member, Span
from quant_stack_v2.exq001 import (
    EXQ001Error,
    _candidate_dependencies,
    _residual_intersection,
    load_registry,
    render_markdown,
)


def test_registry_and_direct_candidate_dependencies_are_frozen() -> None:
    """The scope cannot silently grow from AF-003's seven selected candidates."""
    root = Path(__file__).parents[1]
    registry = load_registry(root / "configs/v2/qualification/exq_001_candidate_scope_v1.yaml")
    dependencies = _candidate_dependencies(root, registry.required_candidate_alpha_ids)
    assert tuple(dependencies) == registry.required_candidate_alpha_ids
    assert set().union(*dependencies.values()) == {"close", "high", "low", "volume"}


def test_residual_intersection_requires_member_signal_and_dependency_role() -> None:
    """A residual symbol/date alone is not an intersection without a candidate dependency."""
    sessions = (
        date(2020, 1, 2),
        date(2020, 1, 3),
        date(2020, 1, 6),
        date(2020, 1, 7),
    )
    residual = {
        "residual": [
            {"symbol": "sz000001", "session": "2020-01-03", "classification": "UNEXPLAINED"},
            {"symbol": "sz000002", "session": "2020-01-03", "classification": "UNEXPLAINED"},
        ]
    }
    rows = _residual_intersection(
        residual,
        (Member(symbol="sz000001", start=sessions[0], end=sessions[3]),),
        sessions,
        (Span(start=sessions[0], end=sessions[3]),),
        {"CN_REV_001": 1},
    )
    assert len(rows) == 1
    assert rows[0]["symbol"] == "sz000001"
    assert {item["dependency_role"] for item in rows[0]["impacts"]} == {
        "FEATURE_LOOKBACK",
        "LABEL_T_PLUS_1",
    }


def test_residual_intersection_rejects_nonblocking_row() -> None:
    """The frozen residual artifact may never silently carry an explained row."""
    with pytest.raises(EXQ001Error, match="nonblocking"):
        _residual_intersection(
            {
                "residual": [
                    {
                        "symbol": "sz000001",
                        "session": "2020-01-02",
                        "classification": "OFFICIAL_SUSPENDED",
                    }
                ]
            },
            (),
            (date(2020, 1, 2),),
            (),
            {},
        )


def test_report_renders_real_newlines() -> None:
    """Human report text must not serialize its line endings as backslash literals."""
    report = render_markdown(
        {
            "status": "BLOCKED_DATA",
            "selected_simple_model": "equal_weight_zscore",
            "ml_challenger": "NO_STABLE_ML_INCREMENT",
            "candidate_alpha_ids": ["CN_REV_001"],
            "required_raw_fields": ["close"],
            "label": "close[T+2] / close[T+1] - 1",
            "scope_membership": {
                "symbol_count": 1,
                "status": "DERIVATIVE_CSI300_MEMBERSHIP_BOUND_NOT_FULL_PIT_QUALIFICATION",
            },
            "lifecycle_and_suspension": {
                "official_suspension_intervals_intersecting_required_range": 0,
                "free_residual_intersection_count": 0,
            },
        },
        "0" * 64,
    )
    assert "\\n" not in report and report.endswith("\n")
