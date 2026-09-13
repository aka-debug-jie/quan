"""Terminal-listing dates are inclusive, independent, and never erase conflicts."""

import json
import subprocess
from hashlib import sha256
from pathlib import Path
from typing import Any

import pytest

from quant_stack_v2.szse_lifecycle import apply_delistings, load_delistings


def evidence(root: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    def store(body: bytes, suffix: str) -> str:
        digest = sha256(body).hexdigest()
        (root / (digest + suffix)).write_bytes(body)
        return digest

    pdf = store(b"fixture pdf", ".pdf")
    catalog = store(
        json.dumps(
            {
                "announcements": [
                    {
                        "announcementId": "1",
                        "secCode": "000562",
                        "announcementTitle": "终止上市公告",
                        "adjunctUrl": "finalpage/2015-01-22/1.PDF",
                    }
                ]
            }
        ).encode(),
        ".catalog.json",
    )
    claim = dict(
        symbol="sz000562",
        issuer_name="宏源证券股份有限公司",
        announcement_id="1",
        official_url="https://static.cninfo.com.cn/finalpage/2015-01-22/1.PDF",
        raw_sha256=pdf,
        catalog_sha256=catalog,
        effective_date="2015-01-26",
        effective_page=1,
        effective_anchor="终止上市日期:2015年1月26日。",
        decision_anchor="深圳证券交易所已同意公司股票自2015年1月26日起终止上市并摘牌。",
        source_kind="ISSUER_NOTICE_REPORTING_EXCHANGE_DECISION",
    )
    text = (
        "证券代码:000562宏源证券股份有限公司。"
        + claim["effective_anchor"]
        + claim["decision_anchor"]
    )
    monkeypatch.setattr(
        "quant_stack_v2.szse_lifecycle.subprocess.run",
        lambda *a, **kw: subprocess.CompletedProcess([], 0, text.encode()),
    )
    digest = store(
        json.dumps(
            dict(scope="SZSE_OFFICIAL_DELISTING_DECISIONS_NOT_PIT", claims=[claim])
        ).encode(),
        ".json",
    )
    return root / (digest + ".json")


def test_effective_date_inclusive_and_conflict_preserved(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    claims = load_delistings(evidence(tmp_path, monkeypatch))
    rows = [
        ["sz000562", "2015-01-23", "UNEXPLAINED"],
        ["sz000562", "2015-01-26", "UNEXPLAINED"],
        ["sz000562", "2015-01-27", "OFFICIAL_SUSPENDED"],
        ["sz000562", "2015-01-28", "CONFLICT"],
        ["sz000001", "2015-01-26", "UNEXPLAINED"],
    ]
    assert [r[2] for r in apply_delistings(rows, claims)] == [
        "UNEXPLAINED",
        "POST_DELISTING",
        "POST_DELISTING",
        "CONFLICT",
        "UNEXPLAINED",
    ]


@pytest.mark.parametrize(
    "change",
    [
        {"effective_date": "2015-01-22"},
        {"decision_anchor": "申请终止上市并摘牌。"},
        {"symbol": "sz000001"},
        {"source_kind": "EXCHANGE_PRIMARY"},
    ],
)
def test_lifecycle_rejects_unbound_dates_and_identity(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, change: dict[str, Any]
) -> None:
    path = evidence(tmp_path, monkeypatch)
    body = json.loads(path.read_bytes())
    body["claims"][0].update(change)
    raw = json.dumps(body).encode()
    invalid = tmp_path / (sha256(raw).hexdigest() + ".json")
    invalid.write_bytes(raw)
    with pytest.raises(ValueError):
        load_delistings(invalid)


def test_replay_does_not_double_count_suspension_on_delisting(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from quant_stack_v2.szse_history_verification import verify

    lifecycle = evidence(tmp_path, monkeypatch)
    monkeypatch.setattr("quant_stack_v2.szse_history_verification.load_histories", lambda p: [])
    baseline = dict(
        source_missing_sessions=2,
        newly_explained_sessions=1,
        newly_explained_by_symbol={"sz000562": 1},
        claims=[],
        membership_gate="BLOCKED_DATA",
        conflict_sessions=0,
        results=[
            dict(
                task=dict(symbol="sz000562", start_session="2015-01-26", end_session="2015-01-27"),
                dates=[
                    dict(
                        session="2015-01-26",
                        classification="ISSUER_CONFIRMED_SUSPENDED",
                        evidence=[],
                    ),
                    dict(session="2015-01-27", classification="UNEXPLAINED", evidence=[]),
                ],
            )
        ],
    )
    monkeypatch.setattr("quant_stack_v2.szse_history_verification.supplement", lambda *a: baseline)
    result = verify(tmp_path / "unused", tmp_path / "unused", tmp_path / "unused", lifecycle)
    assert result["post_delisting_sessions"] == result["covered_sessions"] == 2
    assert result["actual_notice_explained_sessions"] == result["newly_explained_sessions"] == 0
    assert result["gap_gate"] == "PASS" and result["membership_gate"] == "BLOCKED_DATA"
