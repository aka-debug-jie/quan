"""Released date matching must agree with sealed engine logic but never promote gates."""

import json
from hashlib import sha256
from pathlib import Path

import pytest
from test_v2_szse_issuer_supplement import notice_manifest
from test_v2_szse_monthly import fixture

from quant_stack_v2.szse_issuer_supplement import supplement
from quant_stack_v2.szse_local_matching import match_dates
from quant_stack_v2.szse_verification import persist_report, verify_monthly


def test_local_matches_engine_and_remains_non_promoting(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    index, plan, audit, _ = fixture(tmp_path)
    original = verify_monthly(index, plan, audit)
    report = persist_report(original, tmp_path)
    manifest = notice_manifest(tmp_path, monkeypatch)
    source = {
        "scope": "LOCAL_SZSE_MATCHING_DATES_ONLY_NON_PROMOTING",
        "source_report_sha256": report.stem,
        "rows": [
            [r["task"]["symbol"], d["session"], d["classification"]]
            for r in original["results"]
            for d in r["dates"]
        ],
    }
    exported = tmp_path / "released.json"
    exported.write_text(json.dumps(source))
    monkeypatch.setattr(
        "quant_stack_v2.szse_local_matching.RELEASED_DATES_SHA256",
        sha256(exported.read_bytes()).hexdigest(),
    )
    local = match_dates(exported, manifest)
    sealed = supplement(report, manifest)
    for key in (
        "covered_sessions",
        "uncovered_sessions",
        "conflict_sessions",
        "newly_explained_sessions",
    ):
        assert local[key] == sealed[key]
    assert sealed["gap_gate"] == "PASS"
    assert local["gap_gate"] == local["membership_gate"] == "BLOCKED_DATA"
    source["rows"].append(source["rows"][0])
    exported.write_text(json.dumps(source))
    monkeypatch.setattr(
        "quant_stack_v2.szse_local_matching.RELEASED_DATES_SHA256",
        sha256(exported.read_bytes()).hexdigest(),
    )
    with pytest.raises(ValueError, match="duplicate"):
        match_dates(exported, manifest)


def test_resume_day_conflict_and_existing_conflict_are_preserved(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    manifest = notice_manifest(tmp_path, monkeypatch)
    exported = tmp_path / "released.json"
    source = {
        "scope": "LOCAL_SZSE_MATCHING_DATES_ONLY_NON_PROMOTING",
        "source_report_sha256": "fixture",
        "rows": [
            ["sz000001", "2017-08-22", "OFFICIAL_SUSPENDED"],
            ["sz000001", "2017-08-21", "CONFLICT"],
        ],
    }
    exported.write_text(json.dumps(source))
    monkeypatch.setattr(
        "quant_stack_v2.szse_local_matching.RELEASED_DATES_SHA256",
        sha256(exported.read_bytes()).hexdigest(),
    )
    result = match_dates(exported, manifest)
    assert result["conflict_sessions"] == result["uncovered_sessions"] == 2
    assert result["covered_sessions"] == 0
