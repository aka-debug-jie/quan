"""Delisting effective-day classification and claim boundaries."""

import copy

import pytest

from quant_stack_v2.delisting_recovery import parse_notice, reclassify


def test_effective_not_decision_date() -> None:
    text = "2015年5月18日 600832 本所将在2015年5月20日对东方明珠股票予以摘牌 公司股票终止上市"
    assert parse_notice(text, "sh600832") == "2015-05-20"
    with pytest.raises(ValueError):
        parse_notice(text, "sh600005")


def test_inclusive_delisting_keeps_membership_blocked_and_history_unchanged() -> None:
    old = {
        "results": [
            {
                "task": {"symbol": "sh600005"},
                "status": "PARTIAL",
                "covered_dates": ["2017-02-13", "2017-02-14"],
                "uncovered_dates": ["2017-02-15"],
            }
        ]
    }
    frozen = copy.deepcopy(old)
    entries = {"sh600005": {"status": "VERIFIED", "effective_date": "2017-02-14"}}
    result = reclassify(old, entries)
    assert result["post_delisting"] == 2
    assert result["official_suspended"] == 1
    assert result["gap_gate"] == "PASS"
    assert result["membership_gate"] == "BLOCKED_DATA"
    assert old == frozen
    assert reclassify(old, entries) == result
    assert reclassify(old, {})["gap_gate"] == "BLOCKED_DATA"
