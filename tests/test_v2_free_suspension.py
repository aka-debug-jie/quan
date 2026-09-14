"""Offline tests for free missing-session qualification."""

from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest

from quant_stack_v2.baostock_provider import BaoStockRow, capture_baostock_history
from quant_stack_v2.qlib_qualification import QlibDailyIssue
from quant_stack_v2.suspension_audit import (
    MissingClass,
    classify_missing_sessions,
    compress_missing_candidates,
    render_free_evidence_residual_report,
)


def _row(session: date, status: int) -> BaoStockRow:
    return BaoStockRow(session, "sh.600001", "1", "1", "1", "1", "1", "0", "0", status, 0)


def test_baostock_capture_is_raw_unadjusted_and_network_gated(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="allow-network"):
        capture_baostock_history(
            tmp_path,
            symbol="sh600001",
            start_date=date(2020, 1, 1),
            end_date=date(2020, 1, 2),
            allow_network=False,
        )
    rows = [["2020-01-02", "sh.600001", "1", "1", "1", "1", "1", "0", "0", "0", "0"]]
    path, manifest, parsed = capture_baostock_history(
        tmp_path,
        symbol="sh600001",
        start_date=date(2020, 1, 1),
        end_date=date(2020, 1, 2),
        allow_network=True,
        query=lambda *_: ("0", rows),
        provider_version="0.8.9",
    )
    assert path.is_file()
    assert manifest.adjustflag == "3"
    assert parsed[0].tradestatus == 0
    receipt = next((tmp_path / "baostock" / manifest.raw_sha256 / "receipts").glob("*.json"))
    assert '"method":"query_history_k_data_plus"' in receipt.read_text(encoding="utf-8")
    assert '"adjustflag":"3"' in receipt.read_text(encoding="utf-8")


def test_free_audit_compresses_adjacent_market_sessions_and_blocks_conflict() -> None:
    sessions = (date(2020, 1, 2), date(2020, 1, 3), date(2020, 1, 6))
    issues = tuple(
        QlibDailyIssue("sh600001", session.isoformat(), "MISSING_OR_SUSPENDED_UNVERIFIED", "")
        for session in sessions
    )
    evidence = "a" * 64
    report = classify_missing_sessions(
        issues=issues,
        market_sessions=sessions,
        lifecycles={},
        baostock_rows={
            ("sh600001", sessions[0]): (_row(sessions[0], 0), evidence),
            ("sh600001", sessions[1]): (_row(sessions[1], 0), evidence),
            ("sh600001", sessions[2]): (_row(sessions[2], 1), evidence),
        },
    )
    assert report.counts[MissingClass.BAOSTOCK_SUSPENDED.value] == 2
    assert report.counts[MissingClass.PROVIDER_CONFLICT.value] == 1
    assert report.unique_suspension_intervals_count == 1
    assert report.suspension_intervals[0].session_count == 2
    assert report.status == "BLOCKED_DATA"
    assert report.gap_gate == "BLOCKED_DATA"
    candidates = compress_missing_candidates(issues, sessions)
    assert len(candidates) == 1
    assert candidates[0].session_count == 3
    residual = render_free_evidence_residual_report(report)
    assert "PROVIDER_CONFLICT" in residual
    assert "sh600001" in residual


def test_baostock_complete_is_a_free_gate_not_formal_qualification() -> None:
    session = date(2020, 1, 2)
    report = classify_missing_sessions(
        issues=(QlibDailyIssue("sh600001", session.isoformat(), "MISSING", ""),),
        market_sessions=(session,),
        lifecycles={},
        baostock_rows={("sh600001", session): (_row(session, 0), "b" * 64)},
    )
    assert report.gap_gate == "PASS"
    assert report.status == "FREE_EVIDENCE_COMPLETE"


def test_candidate_planning_rejects_non_missing_and_calendar_mismatch() -> None:
    session = date(2020, 1, 2)
    with pytest.raises(ValueError, match="only expected-session"):
        compress_missing_candidates(
            (QlibDailyIssue("sh600001", session.isoformat(), "ILLEGAL_FACTOR", ""),),
            (session,),
        )
    with pytest.raises(ValueError, match="outside"):
        compress_missing_candidates(
            (QlibDailyIssue("sh600001", "2020-01-03", "MISSING_OR_SUSPENDED_UNVERIFIED", ""),),
            (session,),
        )
