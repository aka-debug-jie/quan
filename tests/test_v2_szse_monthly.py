"""Offline SZSE time semantics, provenance and exact daily coverage regressions."""

import json
from datetime import date
from hashlib import sha256
from pathlib import Path

import pytest

from quant_stack_v2.szse_monthly import load_months, parse_month
from quant_stack_v2.szse_verification import match_day, persist_report, verify_monthly

URL = "https://www.szse.cn/market/periodical/documents/example.html"


def table(*rows: tuple[str, str, str], month: str = "2017.08") -> bytes:
    body = f"<table><caption>证券停牌情况 （{month}）</caption>"  # noqa: RUF001
    body += (
        "<tr>"
        + "".join(
            f"<th>{h}</th>" for h in ("代码 Code", "证券简称", "停牌原因", "停牌时间", "复牌时间")
        )
        + "</tr>"
    )
    for symbol, start, resume in rows:
        body += (
            "<tr>"
            + "".join(
                f"<td><span>{c}</span></td>" for c in (symbol, "证券", "重大事项", start, resume)
            )
            + "</tr>"
        )
    return (body + "</table>").encode("gb18030")


def test_open_month_and_intraday_boundaries() -> None:
    events = parse_month(table(("000540", "2017/08/21 09:30", "9999/12/31 00:00")), "2017-08", URL)
    assert events[0].kind == "OPEN"
    assert events[0].full_days() == (date(2017, 8, 21), date(2017, 8, 31))
    assert match_day(list(events), date(2017, 9, 1))["classification"] == "UNEXPLAINED"
    for timing in ("13:00", "盘中即时"):
        event = parse_month(
            table(("000540", f"2017/08/21 {timing}", "9999/12/31 00:00")), "2017-08", URL
        )[0]
        assert event.start_is_intraday
        assert event.full_days()[0] == date(2017, 8, 22)
        assert match_day([event], date(2017, 8, 21))["classification"] == "CONFLICT"
    prior = parse_month(table(("000540", "2017/07/21 09:30", "9999/12/31 00:00")), "2017-08", URL)[
        0
    ]
    assert prior.full_days() == (date(2017, 8, 1), date(2017, 8, 31))


def test_actual_resume_cross_month_and_disagreement() -> None:
    events = list(
        parse_month(table(("000540", "2017/08/21 09:30", "9999/12/31 00:00")), "2017-08", URL)
    )
    events += list(
        parse_month(
            table(("000540", "2017/08/21 09:30", "2017/09/05 09:30"), month="2017.09"),
            "2017-09",
            URL,
        )
    )
    assert match_day(events, date(2017, 9, 4))["classification"] == "OFFICIAL_SUSPENDED"
    assert match_day(events, date(2017, 9, 5))["classification"] == "CONFLICT"
    assert match_day(events, date(2017, 9, 6))["classification"] == "UNEXPLAINED"
    events += list(
        parse_month(table(("000540", "2017/08/21 09:30", "2017/08/25 09:30")), "2017-08", URL)
    )
    assert match_day(events, date(2017, 8, 23))["reason"] == "ACTUAL_RESUME_DISAGREEMENT"


def test_new_event_cuts_stale_open_evidence() -> None:
    events = list(
        parse_month(
            table(
                ("000540", "2017/08/01 09:30", "9999/12/31 00:00"),
                ("000540", "2017/08/03 09:30", "2017/08/03 10:30"),
            ),
            "2017-08",
            URL,
        )
    )
    assert events[1].kind == "INTRADAY"
    assert match_day(events, date(2017, 8, 2))["classification"] == "OFFICIAL_SUSPENDED"
    assert match_day(events, date(2017, 8, 3))["classification"] == "CONFLICT"
    assert match_day(events, date(2017, 8, 4))["classification"] == "UNEXPLAINED"


@pytest.mark.parametrize(
    "start,resume",
    [
        ("2017/08/21 unknown", "9999/12/31 00:00"),
        ("2017/08/21 09:30", "2017/08/20 09:30"),
        ("2017/08/21 09:30", "9999/12/31 09:30"),
    ],
)
def test_invalid_timestamps(start: str, resume: str) -> None:
    with pytest.raises(ValueError):
        parse_month(table(("000540", start, resume)), "2017-08", URL)


def test_schema_and_utf8() -> None:
    raw = table(("000540", "2017/08/21 09:30", "9999/12/31 00:00"))
    assert parse_month(raw.decode("gb18030").encode(), "2017-08", URL)
    with pytest.raises(ValueError, match="month"):
        parse_month(raw, "2017-09", URL)
    with pytest.raises(ValueError, match="columns"):
        parse_month(raw.decode("gb18030").replace("复牌时间", "未知").encode(), "2017-08", URL)
    with pytest.raises(ValueError, match="row"):
        parse_month(raw.replace(b"000540", b"540"), "2017-08", URL)


def hashed(root: Path, value: object) -> Path:
    body = json.dumps(value, sort_keys=True).encode() + b"\n"
    path = root / (sha256(body).hexdigest() + ".json")
    path.write_bytes(body)
    return path


def fixture(tmp_path: Path) -> tuple[Path, Path, Path, Path]:
    raw = table(("000540", "2017/08/21 09:30", "2017/08/24 09:30"))
    digest = sha256(raw).hexdigest()
    raw_path = tmp_path / "raw" / digest / "body.html"
    raw_path.parent.mkdir(parents=True)
    raw_path.write_bytes(raw)
    index = hashed(
        tmp_path,
        {
            "months": [
                {
                    "month": "2017-08",
                    "status": "CAPTURED_NOT_QUALIFIED",
                    "table": {
                        "sha256": digest,
                        "url": URL,
                        "final_url": URL,
                        "path": "/must/not/use",
                    },
                }
            ]
        },
    )
    dates = {"sz000540": ["2017-08-21", "2017-08-22"], "sz000001": ["2017-08-21"]}
    audit = hashed(
        tmp_path,
        {
            "issues": [
                {"kind": "MISSING_OR_SUSPENDED_UNVERIFIED", "symbol": s, "session": d}
                for s, ds in dates.items()
                for d in ds
            ]
        },
    )
    plan = hashed(
        tmp_path,
        {
            "audit_sha256": sha256(audit.read_bytes()).hexdigest(),
            "intervals": [
                {
                    "exchange": "SZ",
                    "symbol": s,
                    "start_session": ds[0],
                    "end_session": ds[-1],
                    "session_count": len(ds),
                }
                for s, ds in dates.items()
            ],
        },
    )
    return index, plan, audit, raw_path


def test_verifier_exact_dates_and_immutable_report(tmp_path: Path) -> None:
    index, plan, audit, _ = fixture(tmp_path)
    result = verify_monthly(index, plan, audit)
    assert result["interval_counts"] == {"FULL": 1, "PARTIAL": 0, "NO_MATCH": 1, "CONFLICT": 0}
    assert result["covered_sessions"] == 2
    assert result["missing_sessions"] == 3
    assert len(result["residual"]) == 1
    assert result["membership_gate"] == "BLOCKED_DATA"
    assert result == verify_monthly(index, plan, audit)
    output = persist_report(result, tmp_path)
    assert output == persist_report(result, tmp_path)
    assert output.stem == sha256(output.read_bytes()).hexdigest()
    data = json.loads(plan.read_bytes())
    data["intervals"] = data["intervals"][:1]
    with pytest.raises(ValueError, match="all SZSE"):
        verify_monthly(index, hashed(tmp_path, data), audit)
    data["intervals"] *= 2
    with pytest.raises(ValueError, match="overlaps"):
        verify_monthly(index, hashed(tmp_path, data), audit)
    data["audit_sha256"] = "0" * 64
    with pytest.raises(ValueError, match="binding"):
        verify_monthly(index, hashed(tmp_path, data), audit)


def test_tamper_and_duplicate_month(tmp_path: Path) -> None:
    index, plan, audit, raw = fixture(tmp_path)
    data = json.loads(index.read_bytes())
    data["months"] *= 2
    with pytest.raises(ValueError, match="duplicate"):
        load_months(hashed(tmp_path, data))
    raw.write_bytes(b"tampered")
    with pytest.raises(ValueError, match="raw table"):
        verify_monthly(index, plan, audit)
    index.write_bytes(b"tampered")
    with pytest.raises(ValueError, match="index"):
        load_months(index)


def test_partial_conflict_and_membership_gate_stays_blocked(tmp_path: Path) -> None:
    index, plan, _, _ = fixture(tmp_path)
    data = json.loads(plan.read_bytes())
    for dates, expected, covered in (
        (["2017-08-21", "2017-08-25"], "PARTIAL", 1),
        (["2017-08-21", "2017-08-24"], "CONFLICT", 1),
        (["2017-08-21", "2017-08-22"], "FULL", 2),
    ):
        audit = hashed(
            tmp_path,
            {
                "issues": [
                    {"symbol": "sz000540", "session": d, "kind": "MISSING_OR_SUSPENDED_UNVERIFIED"}
                    for d in dates
                ]
            },
        )
        data["audit_sha256"] = sha256(audit.read_bytes()).hexdigest()
        data["intervals"] = [
            {
                "symbol": "sz000540",
                "exchange": "SZ",
                "start_session": dates[0],
                "end_session": dates[-1],
                "session_count": 2,
            }
        ]
        result = verify_monthly(index, hashed(tmp_path, data), audit)
        assert result["interval_counts"][expected] == 1
        assert result["covered_sessions"] == covered
        assert result["covered_sessions"] + result["uncovered_sessions"] == 2
        assert result["membership_gate"] == "BLOCKED_DATA"
        assert result["gap_gate"] == ("PASS" if expected == "FULL" else "BLOCKED_DATA")


def test_archive_url_validation(tmp_path: Path) -> None:
    index, _, _, _ = fixture(tmp_path)
    data = json.loads(index.read_bytes())
    data["months"][0]["table"]["final_url"] = "https://unofficial.example/table"
    with pytest.raises(ValueError, match="non-official"):
        load_months(hashed(tmp_path, data))


def test_cli_parse_and_match(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    from quant_stack_v2.szse_verification import main

    index, plan, audit, _ = fixture(tmp_path)
    common = ["szse", "--index", str(index), "--output-root", str(tmp_path / "output")]
    monkeypatch.setattr("sys.argv", common)
    with pytest.raises(SystemExit) as exit_info:
        main()
    assert exit_info.value.code == 0
    assert json.loads(capsys.readouterr().out)["gap_gate"] == "NOT_RUN"
    monkeypatch.setattr(
        "sys.argv",
        [
            *common,
            "--plan",
            str(plan),
            "--audit",
            str(audit),
            "--expected-intervals",
            "2",
            "--expected-sessions",
            "3",
        ],
    )
    with pytest.raises(SystemExit) as exit_info:
        main()
    assert exit_info.value.code == 1
    assert json.loads(capsys.readouterr().out)["gap_gate"] == "BLOCKED_DATA"
    monkeypatch.setattr(
        "sys.argv",
        [*common, "--plan", str(plan), "--audit", str(audit), "--expected-sessions", "8093"],
    )
    with pytest.raises(ValueError, match="session count"):
        main()
