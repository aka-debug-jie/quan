"""Bounded histories cannot turn planned resumptions into actual trading evidence."""

import json
import subprocess
from datetime import datetime, timedelta, timezone
from hashlib import sha256
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from quant_stack_v2.szse_history import _signed_matches, apply_histories, load_histories


def store(root: Path, body: bytes, suffix: str) -> Path:
    path = root / (sha256(body).hexdigest() + suffix)
    path.write_bytes(body)
    return path


def fixture(root: Path, monkeypatch: pytest.MonkeyPatch, **changes: Any) -> Path:
    monkeypatch.setattr("quant_stack_v2.szse_history.load_months", lambda p: ())
    pdf = store(root, b"fixture PDF", ".pdf")
    catalog = store(
        root,
        json.dumps(
            {
                "announcements": [
                    {
                        "announcementId": "1",
                        "secCode": "000001",
                        "announcementTitle": "复牌公告",
                        "adjunctUrl": "finalpage/2017-10-27/1.PDF",
                        "announcementTime": int(
                            datetime(2017, 10, 27, tzinfo=timezone(timedelta(hours=8))).timestamp()
                            * 1000
                        ),
                    }
                ]
            }
        ).encode(),
        ".catalog.json",
    )
    text = (
        "证券代码:000001示例股份有限公司。公司股票自2017年1月16日起停牌。"
        "停牌期间公司持续披露进展。公司股票将继续停牌。"
        "公司股票将于2017年10月27日复牌。二零一七年十月二十六日"
    )
    monkeypatch.setattr(
        "quant_stack_v2.szse_history.subprocess.run",
        lambda *a, **kw: subprocess.CompletedProcess([], 0, text.encode()),
    )
    claim = {
        "symbol": "sz000001",
        "issuer_name": "示例股份有限公司",
        "announcement_id": "1",
        "official_url": "https://static.cninfo.com.cn/finalpage/2017-10-27/1.PDF",
        "raw_sha256": pdf.stem,
        "catalog_sha256": catalog.name.split(".")[0],
        "start_date": "2017-01-16",
        "signed_date": "2017-10-26",
        "planned_resume_date": "2017-10-27",
        "evidence_cutoff_exclusive": "2017-10-27",
        "actual_resume_date": None,
        "closed_actual": False,
        "right_censored": True,
        "start_anchor": "公司股票自2017年1月16日起停牌。",
        "continuity_anchor": "停牌期间公司持续披露进展。",
        "planned_anchor": "公司股票将于2017年10月27日复牌。",
        "signed_anchor": "二零一七年十月二十六日",
        **{k + "_page": 1 for k in ("start", "continuity", "planned", "signed")},
        **changes,
    }
    return store(
        root,
        json.dumps({"scope": "REVIEWED_DATED_SUSPENSION_HISTORY", "claims": [claim]}).encode(),
        ".json",
    )


def test_shanghai_date_and_exclusive_boundaries(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    histories = load_histories(fixture(tmp_path, monkeypatch))
    rows = [
        ["sz000001", d, "UNEXPLAINED"]
        for d in ("2017-01-16", "2017-10-26", "2017-10-27", "2017-10-30")
    ]
    output, changes = apply_histories(rows, histories, [])
    assert [r[2] for r in output] == [
        "UNEXPLAINED",
        "ISSUER_CONFIRMED_HISTORY",
        "UNEXPLAINED",
        "UNEXPLAINED",
    ]
    assert len(changes) == 1
    assert histories[0]["actual_resume_date"] is None


@pytest.mark.parametrize(
    "changes",
    [
        {"evidence_cutoff_exclusive": "2017-10-28"},
        {"signed_date": "2017-10-20"},
        {"signed_date": "2017-10-27"},
        {"actual_resume_date": "2017-10-27"},
        {"closed_actual": True},
        {"right_censored": False},
        {"continuity_anchor": "目前没有更多消息"},
    ],
)
def test_history_rejects_extension_and_false_actual(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, changes: dict[str, Any]
) -> None:
    with pytest.raises(ValueError):
        load_histories(fixture(tmp_path, monkeypatch, **changes))


def test_conflicts_and_known_actual_resume_block_history(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    histories = load_histories(fixture(tmp_path, monkeypatch))
    rows = [["sz000001", "2017-10-25", "CONFLICT"], ["sz000001", "2017-10-26", "UNEXPLAINED"]]
    result, changes = apply_histories(
        rows, histories, [{"symbol": "sz000001", "resume_date": "2017-10-20"}]
    )
    assert result == rows and not changes


def test_monthly_resumption_blocks_cross_event_history(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = fixture(tmp_path, monkeypatch)
    monkeypatch.setattr(
        "quant_stack_v2.szse_history.load_months",
        lambda p: [
            SimpleNamespace(
                symbol="sz000001", start=datetime(2017, 1, 16), resume=datetime(2017, 5, 1)
            )
        ],
    )
    with pytest.raises(ValueError, match="monthly actual"):
        load_histories(path)


def test_adjacent_page_fragments_exclude_printed_page_number(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = fixture(
        tmp_path,
        monkeypatch,
        planned_fragments=[
            {"page": 1, "anchor": "公司股票将于2017年10月27"},
            {"page": 2, "anchor": "日复牌。"},
        ],
    )
    text = (
        "证券代码:000001示例股份有限公司。公司股票自2017年1月16日起停牌。"
        "停牌期间公司持续披露进展。二零一七年十月二十六日"
        "公司股票将于2017年10月27\n1\f日复牌。"
    )
    monkeypatch.setattr(
        "quant_stack_v2.szse_history.subprocess.run",
        lambda *a, **kw: subprocess.CompletedProcess([], 0, text.encode()),
    )
    assert len(load_histories(path)) == 1
    bad_text = text.replace("27\n1\f", "27其他正文\n1\f")
    monkeypatch.setattr(
        "quant_stack_v2.szse_history.subprocess.run",
        lambda *a, **kw: subprocess.CompletedProcess([], 0, bad_text.encode()),
    )
    with pytest.raises(ValueError, match="end page body"):
        load_histories(path)
    data = json.loads(path.read_bytes())
    data["claims"][0]["planned_fragments"][1]["page"] = 3
    invalid = store(tmp_path, json.dumps(data).encode(), ".json")
    with pytest.raises(ValueError, match="adjacent"):
        load_histories(invalid)
    data = json.loads(path.read_bytes())
    data["claims"][0]["planned_page"] = 2
    invalid = store(tmp_path, json.dumps(data).encode(), ".json")
    with pytest.raises(ValueError, match="first fragment"):
        load_histories(invalid)
    data = json.loads(path.read_bytes())
    data["claims"][0]["planned_fragments"][1]["anchor"] = ""
    invalid = store(tmp_path, json.dumps(data).encode(), ".json")
    with pytest.raises(ValueError, match="non-empty"):
        load_histories(invalid)


def test_signature_mixed_zero_preserves_numeric_dates() -> None:
    from datetime import date

    assert _signed_matches("二0一五年七月二十一日", date(2015, 7, 21))
    assert _signed_matches("2015年7月21日", date(2015, 7, 21))
    assert not _signed_matches("二0一五年七月二十日", date(2015, 7, 21))


def test_continuing_state_history_uses_only_the_observed_boundary(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = fixture(
        tmp_path,
        monkeypatch,
        planned_resume_date=None,
        evidence_kind="CONTINUING_SUSPENSION_STATE",
        evidence_cutoff_exclusive="2017-10-27",
        continuity_anchor="公司股票将继续停牌。",
    )
    histories = load_histories(path)
    _, changes = apply_histories([["sz000001", "2017-10-26", "UNEXPLAINED"]], histories, [])
    assert len(changes) == 1
    body = json.loads(path.read_bytes())
    body["claims"][0]["evidence_cutoff_exclusive"] = "2017-10-26"
    invalid = store(tmp_path, json.dumps(body).encode(), ".json")
    with pytest.raises(ValueError, match="observed boundary"):
        load_histories(invalid)


def test_continuing_state_rejects_completed_resumption_in_claimed_window(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = fixture(
        tmp_path,
        monkeypatch,
        planned_resume_date=None,
        evidence_kind="CONTINUING_SUSPENSION_STATE",
        evidence_cutoff_exclusive="2017-10-27",
        continuity_anchor="公司股票将继续停牌。",
    )
    text = (
        "证券代码:000001示例股份有限公司。公司股票自2017年1月16日起停牌。"
        "公司股票将继续停牌。公司股票已于2017年10月20日复牌。"
        "二零一七年十月二十六日"
    )
    monkeypatch.setattr(
        "quant_stack_v2.szse_history.subprocess.run",
        lambda *a, **kw: subprocess.CompletedProcess([], 0, text.encode()),
    )
    with pytest.raises(ValueError, match="completed resumption"):
        load_histories(path)


def test_same_notice_bounded_pair_requires_both_anchors(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    text = (
        "证券代码:000001示例股份有限公司。公司股票自2017年1月16日起停牌。"
        "公司股票将于2017年10月27日复牌。二零一七年十月二十六日"
    )
    path = fixture(
        tmp_path,
        monkeypatch,
        evidence_kind="BOUNDED_START_TO_PLANNED_BOUNDARY",
        continuity_anchor=text,
    )
    monkeypatch.setattr(
        "quant_stack_v2.szse_history.subprocess.run",
        lambda *a, **kw: subprocess.CompletedProcess([], 0, text.encode()),
    )
    histories = load_histories(path)
    _, changes = apply_histories(
        [["sz000001", "2017-10-26", "UNEXPLAINED"], ["sz000001", "2017-10-27", "UNEXPLAINED"]],
        histories,
        [],
    )
    assert len(changes) == 1
    body = json.loads(path.read_bytes())
    body["claims"][0]["continuity_anchor"] = "公司股票将于2017年10月27日复牌。"
    invalid = store(tmp_path, json.dumps(body).encode(), ".json")
    with pytest.raises(ValueError, match="same-notice"):
        load_histories(invalid)
    bad = text + "公司股票已于2017年10月20日复牌。"
    monkeypatch.setattr(
        "quant_stack_v2.szse_history.subprocess.run",
        lambda *a, **kw: subprocess.CompletedProcess([], 0, bad.encode()),
    )
    with pytest.raises(ValueError, match="completed resumption"):
        load_histories(path)


def test_explicit_continuous_state_wording() -> None:
    from quant_stack_v2.szse_history import _explicit_continuing_state

    assert _explicit_continuing_state("本公司股票(股票代码:000562)已自2014年12月10日开始连续停牌")
    assert not _explicit_continuing_state("本公司股票。其他证券继续停牌")
