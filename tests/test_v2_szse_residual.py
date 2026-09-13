"""Offline residual leads preserve evidence boundaries and all residual dates."""

import json
from datetime import date
from pathlib import Path

import pytest
from test_v2_szse_monthly import URL, fixture, hashed, table

from quant_stack_v2.szse_monthly import parse_month
from quant_stack_v2.szse_residual import diagnose, evidence_hint, main
from quant_stack_v2.szse_verification import persist_report, verify_monthly


def test_cross_month_lead_is_not_indefinite_suspension() -> None:
    events = list(
        parse_month(table(("000540", "2017/08/21 09:30", "9999/12/31 00:00")), "2017-08", URL)
    )
    months = {"2017-08", "2017-09"}
    assert (
        evidence_hint(events, date(2017, 9, 1), months)
        == "PRIOR_MONTH_OPEN_NEEDS_CONTINUATION_PROOF"
    )
    assert evidence_hint(events, date(2017, 8, 1), months) == "NO_EARLIER_SUSPENSION_RECORD"
    assert evidence_hint(events, date(2017, 8, 22), months) == "OTHER_UNEXPLAINED"
    assert evidence_hint([], date(2017, 9, 1), months) == "NO_SYMBOL_RECORD"
    assert evidence_hint(events, date(2017, 10, 1), months) == "OUTSIDE_ARCHIVED_MONTHS"
    events += list(
        parse_month(table(("000540", "2017/08/21 09:30", "2017/08/28 09:30")), "2017-08", URL)
    )
    assert evidence_hint(events, date(2017, 9, 1), months) == "OTHER_UNEXPLAINED"


def test_report_binding_and_residual_accounting(tmp_path: Path) -> None:
    index, plan, audit, _ = fixture(tmp_path)
    original = verify_monthly(index, plan, audit)
    report = persist_report(original, tmp_path)
    output = diagnose(report, index)
    assert output["residual_sessions"] == 1
    assert output["lead_counts"] == {"NO_SYMBOL_RECORD": 1}
    assert output["no_match_intervals"][0]["symbol"] == "sz000001"
    assert output["gap_gate"] == output["membership_gate"] == "BLOCKED_DATA"
    assert output["newly_explained_sessions"] == 0
    assert sum(t["session_count"] for t in output["tasks"]) == 1
    assert diagnose(report, index) == output
    original["residual"] *= 2
    with pytest.raises(ValueError, match="count"):
        diagnose(persist_report(original, tmp_path), index)
    report.write_bytes(b"tamper")
    with pytest.raises(ValueError, match="SHA-256"):
        diagnose(report, index)


def test_grouping_splits_at_covered_dates(tmp_path: Path) -> None:
    index, plan, _, _ = fixture(tmp_path)
    payload = json.loads(plan.read_bytes())
    dates = ["2017-08-18", "2017-08-21", "2017-08-22", "2017-08-25", "2017-08-28"]
    audit = hashed(
        tmp_path,
        {
            "issues": [
                {"symbol": "sz000540", "session": d, "kind": "MISSING_OR_SUSPENDED_UNVERIFIED"}
                for d in dates
            ]
        },
    )
    from hashlib import sha256

    payload["audit_sha256"] = sha256(audit.read_bytes()).hexdigest()
    payload["intervals"] = [
        {
            "symbol": "sz000540",
            "exchange": "SZ",
            "start_session": dates[0],
            "end_session": dates[-1],
            "session_count": len(dates),
        }
    ]
    original = verify_monthly(index, hashed(tmp_path, payload), audit)
    output = diagnose(persist_report(original, tmp_path), index)
    assert output["residual_sessions"] == 3
    assert [t["session_count"] for t in output["tasks"]] == [1, 2]
    assert output["tasks"][1]["start_session"] == "2017-08-25"
    assert output["tasks"][1]["nearest_prior_event"]["resume"] == "2017-08-24T09:30:00"


@pytest.mark.parametrize(
    "field,value",
    [
        ("index_sha256", "0" * 64),
        ("source_sha256", {"szse_monthly.py": "0" * 64}),
        ("scope", "OTHER"),
    ],
)
def test_wrong_input_or_code_binding(tmp_path: Path, field: str, value: object) -> None:
    index, plan, audit, _ = fixture(tmp_path)
    original = verify_monthly(index, plan, audit)
    original[field] = value
    with pytest.raises(ValueError):
        diagnose(persist_report(original, tmp_path), index)


def test_cli_summary(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    index, plan, audit, _ = fixture(tmp_path)
    report = persist_report(verify_monthly(index, plan, audit), tmp_path)
    args = [
        "diagnose",
        "--report",
        str(report),
        "--index",
        str(index),
        "--output-root",
        str(tmp_path / "out"),
        "--expected-residuals",
        "1",
    ]
    monkeypatch.setattr("sys.argv", args)
    main()
    summary = json.loads(capsys.readouterr().out)
    assert summary["residual_sessions"] == 1
    assert "tasks" not in summary
    assert "nearest_prior_event" not in summary["top_tasks"][0]
    assert Path(summary["report_path"]).is_file()
    monkeypatch.setattr("sys.argv", [*args[:-1], "6027"])
    with pytest.raises(ValueError, match="unexpected"):
        main()
