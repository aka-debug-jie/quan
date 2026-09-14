"""Regression tests for V2 Foundation Gate evidence handling."""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path

import pytest

from quant_stack_v2.csi_membership import OfficialMembershipInterval, reconcile_official_membership
from quant_stack_v2.foundation_gate import GateEvidence, qualify_foundation
from quant_stack_v2.qlib_import import QlibInstrumentInterval
from quant_stack_v2.tushare_pro import capture_tushare_response


def test_foundation_gate_blocks_absent_and_failed_evidence() -> None:
    report = qualify_foundation(
        universe="csi300",
        research_effective_from="2015-01-01",
        research_effective_to="2026-09-10",
        import_report_sha256="a" * 64,
        config_sha256="b" * 64,
        code_commit="c" * 40,
        evidence=(GateEvidence("factor_semantics", "x", "d" * 64, "QUALIFIED"),),
    )
    assert report.status == "BLOCKED_DATA"
    assert "official_membership_missing" in report.reasons
    assert "free_evidence_reconciliation_missing" in report.reasons
    assert "tushare_raw_reconciliation_missing" not in report.reasons


def test_tushare_is_an_optional_provider_gate() -> None:
    report = qualify_foundation(
        universe="csi300",
        research_effective_from="2015-01-01",
        research_effective_to="2026-09-10",
        import_report_sha256="a" * 64,
        config_sha256="b" * 64,
        code_commit="c" * 40,
        evidence=(GateEvidence("tushare_raw_reconciliation", "x", "d" * 64, "UNAVAILABLE"),),
    )
    assert "tushare_raw_reconciliation_not_qualified" not in report.reasons


def test_tushare_capture_needs_network_and_runtime_token(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="allow-network"):
        capture_tushare_response(
            tmp_path, api_name="daily", parameters={}, allow_network=False, token="token"
        )
    with pytest.raises(ValueError, match="TUSHARE_TOKEN"):
        capture_tushare_response(tmp_path, api_name="daily", parameters={}, allow_network=True)
    response = json.dumps({"code": 0, "data": {"fields": [], "items": []}}).encode()
    path, manifest = capture_tushare_response(
        tmp_path,
        api_name="daily",
        parameters={"ts_code": "000001.SZ"},
        allow_network=True,
        token="token",
        fetcher=lambda _: (response, {":status": "200"}),
    )
    assert path.is_file()
    assert manifest.status == "CAPTURED"


def test_official_membership_requires_exact_daily_match() -> None:
    official = OfficialMembershipInterval(
        symbol="sz000001",
        effective_from=date(2015, 1, 1),
        effective_to=date(2015, 1, 2),
        source_url="https://www.csindex.com.cn/example.pdf",
        published_on=date(2014, 12, 31),
        source_sha256="a" * 64,
        locator="page 1",
        parser_version="1",
    )
    result = reconcile_official_membership(
        universe="csi300",
        qlib_import_sha256="b" * 64,
        qlib_intervals=(QlibInstrumentInterval("sz000001", date(2015, 1, 1), date(2015, 1, 1)),),
        official_intervals=(official,),
        sessions=(date(2015, 1, 1), date(2015, 1, 2)),
        research_effective_from=date(2015, 1, 1),
        research_effective_to=date(2015, 1, 2),
    )
    assert result.status == "BLOCKED_DATA"
    assert result.mismatched_sessions == ("2015-01-02",)
