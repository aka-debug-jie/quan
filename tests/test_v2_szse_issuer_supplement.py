"""Issuer notice regressions: actual wording, PDF hashes, boundaries and gate isolation."""

import json
import subprocess
from datetime import date
from hashlib import sha256
from pathlib import Path

import pytest
from test_v2_szse_monthly import fixture, hashed

from quant_stack_v2.szse_issuer_supplement import load_claims, supplement, verify_notice_text
from quant_stack_v2.szse_verification import persist_report, verify_monthly


def claim() -> dict[str, object]:
    return {
        "symbol": "sz000001",
        "start_date": "2017-08-18",
        "resume_date": "2017-08-22",
        "start_page": 1,
        "resume_page": 1,
        "start_anchor": "公司股票自2017年8月18日起停牌。",
        "resume_anchor": "公司股票于2017年8月22日开市起复牌。",
        "official_url": "https://static.cninfo.com.cn/finalpage/2017-08-30/example.PDF",
    }


def pages() -> list[str]:
    return ["证券代码:000001\n公司股票自2017年8月18日起停牌。公司股票于2017年8月22日开市起复牌。"]


def test_actual_dates_exclude_unverified_start_timing_and_resume_day() -> None:
    assert verify_notice_text(pages(), claim()) == (date(2017, 8, 19), date(2017, 8, 21))


@pytest.mark.parametrize("word", ["拟于", "将于", "预计于", "申请于"])
def test_planned_resume_is_rejected(word: str) -> None:
    c = claim()
    c["resume_anchor"] = str(c["resume_anchor"]).replace("股票于", "股票" + word)
    with pytest.raises(ValueError, match="actual resumption"):
        verify_notice_text([pages()[0].replace("股票于", "股票" + word)], c)


@pytest.mark.parametrize(
    "changes",
    [
        {"symbol": "sz000002"},
        {"start_date": "2017-08-19"},
        {"resume_date": "2017-08-18"},
        {"resume_page": 2},
        {"resume_anchor": "公司股票于2017年8月23日开市起复牌。"},
    ],
)
def test_wrong_identity_anchor_or_dates(changes: dict[str, object]) -> None:
    with pytest.raises(ValueError):
        verify_notice_text(pages(), claim() | changes)


def notice_manifest(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    raw = b"%PDF-fake-archived-test-fixture"
    digest = sha256(raw).hexdigest()
    (tmp_path / (digest + ".pdf")).write_bytes(raw)

    def extract(*args: object, **kwargs: object) -> subprocess.CompletedProcess[bytes]:
        return subprocess.CompletedProcess([], 0, stdout="\f".join(pages()).encode())

    monkeypatch.setattr("quant_stack_v2.szse_issuer_supplement.subprocess.run", extract)
    return hashed(tmp_path, {"claims": [claim() | {"raw_sha256": digest}]})


def test_pdf_tamper_and_source_identity(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    manifest = notice_manifest(tmp_path, monkeypatch)
    claims, _ = load_claims(manifest)
    assert claims[0]["first_full_session"] == "2017-08-19"
    next(tmp_path.glob("*.pdf")).write_bytes(b"tamper")
    with pytest.raises(ValueError, match="PDF SHA"):
        load_claims(manifest)
    manifest.write_bytes(b"tamper")
    with pytest.raises(ValueError, match="manifest SHA"):
        load_claims(manifest)


def test_supplement_counts_and_membership_never_promoted(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    index, plan, audit, _ = fixture(tmp_path)
    original = verify_monthly(index, plan, audit)
    report = persist_report(original, tmp_path)
    before = report.read_bytes()
    manifest = notice_manifest(tmp_path, monkeypatch)
    result = supplement(report, manifest)
    assert result["newly_explained_sessions"] == 1
    assert result["covered_sessions"] == 3
    assert result["interval_counts"]["FULL"] == 2
    assert result["gap_gate"] == "PASS"
    assert result["membership_gate"] == "BLOCKED_DATA"
    assert report.read_bytes() == before
    assert supplement(report, manifest) == result
    assert result["original_covered_sessions"] == 2


def test_existing_conflict_is_not_overwritten(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    index, plan, audit, _ = fixture(tmp_path)
    original = verify_monthly(index, plan, audit)
    for r in original["results"]:
        if r["task"]["symbol"] == "sz000001":
            r["dates"][0]["classification"] = "CONFLICT"
    manifest = notice_manifest(tmp_path, monkeypatch)
    result = supplement(persist_report(original, tmp_path), manifest)
    assert result["newly_explained_sessions"] == 0
    assert result["conflict_sessions"] == 1
    assert result["gap_gate"] == "BLOCKED_DATA"


def test_resume_day_revokes_conflicting_monthly_coverage(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    index, plan, audit, _ = fixture(tmp_path)
    original = verify_monthly(index, plan, audit)
    manifest = notice_manifest(tmp_path, monkeypatch)
    c = json.loads(manifest.read_bytes())["claims"][0]
    c["symbol"] = "sz000540"
    monkeypatch.setattr(
        "quant_stack_v2.szse_issuer_supplement.subprocess.run",
        lambda *a, **k: subprocess.CompletedProcess(
            [], 0, stdout=pages()[0].replace("000001", "000540").encode()
        ),
    )
    result = supplement(persist_report(original, tmp_path), hashed(tmp_path, {"claims": [c]}))
    assert result["conflict_sessions"] == 1
    assert result["notice_conflicts"][0]["session"] == "2017-08-22"
    assert result["covered_sessions"] == 1
    assert result["gap_gate"] == "BLOCKED_DATA"


def test_identity_document_binds_same_issuer(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    manifest = notice_manifest(tmp_path, monkeypatch)
    c = json.loads(manifest.read_bytes())["claims"][0]
    c.update(
        issuer_name="测试发行人",
        identity_raw_sha256=c["raw_sha256"],
        identity_official_url=c["official_url"],
    )
    text = "测试发行人" + pages()[0]
    monkeypatch.setattr(
        "quant_stack_v2.szse_issuer_supplement.subprocess.run",
        lambda *a, **k: subprocess.CompletedProcess([], 0, stdout=text.encode()),
    )
    assert load_claims(hashed(tmp_path, {"claims": [c]}))[0][0]["symbol"] == "sz000001"
    with pytest.raises(ValueError, match="cross-notice"):
        verify_notice_text(["错误公司" + pages()[0]], c, [text])
    c["identity_official_url"] = "https://example.invalid/source.pdf"
    with pytest.raises(ValueError, match="non-official"):
        load_claims(hashed(tmp_path, {"claims": [c]}))


def test_combined_past_tense_sentence() -> None:
    c = claim()
    c["resume_anchor"] = "公司股票于2017年8月18日停牌,于2017年8月22日开市起复牌。"
    text = pages()[0] + str(c["resume_anchor"])
    assert verify_notice_text([text], c)[1] == date(2017, 8, 21)
    c["resume_anchor"] = str(c["resume_anchor"]).replace(",于", ",将于")
    with pytest.raises(ValueError, match="actual resumption"):
        verify_notice_text([text + str(c["resume_anchor"])], c)


def test_cli_writes_report(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    from quant_stack_v2.szse_issuer_supplement import main

    index, plan, audit, _ = fixture(tmp_path)
    report = persist_report(verify_monthly(index, plan, audit), tmp_path)
    manifest = notice_manifest(tmp_path, monkeypatch)
    monkeypatch.setattr(
        "sys.argv",
        [
            "supplement",
            "--report",
            str(report),
            "--manifest",
            str(manifest),
            "--output-root",
            str(tmp_path / "output"),
            "--all-residual-tasks",
        ],
    )
    with pytest.raises(SystemExit) as exit_info:
        main()
    assert exit_info.value.code == 0
    output = json.loads(capsys.readouterr().out)
    assert Path(output["report_path"]).exists()
    assert output["residual_evidence_queue"]["residual_sessions"] == 0
    assert output["residual_evidence_queue"]["rows"] == []
    assert output["top_residual_tasks"] == []
    assert output["membership_gate"] == "BLOCKED_DATA"


@pytest.mark.parametrize("prefix", ["公司拟向深交所申请", "假设", "预计", "若"])
def test_planned_context_cannot_be_removed_from_anchor(prefix: str) -> None:
    c = claim()
    text = pages()[0].replace("公司股票于2017年8月22日", prefix + "公司股票于2017年8月22日")
    with pytest.raises(ValueError, match="sentence context"):
        verify_notice_text([text], c)


@pytest.mark.parametrize(
    "anchor",
    [
        "公司股票2017年8月22日开市起复牌。",
        "公司股票自2017年8月18日起停牌,于2017年8月22日复牌。",
    ],
)
def test_reviewed_retrospective_wording_variants(anchor: str) -> None:
    c = claim()
    c["resume_anchor"] = anchor
    assert verify_notice_text([pages()[0] + anchor], c)[1] == date(2017, 8, 21)


@pytest.mark.parametrize("prefix", ["公司拟申请", "公司计划", "假设"])
def test_new_wording_still_rejects_planned_context(prefix: str) -> None:
    c = claim()
    c["resume_anchor"] = "公司股票2017年8月22日开市起复牌。"
    with pytest.raises(ValueError, match="sentence context"):
        verify_notice_text([pages()[0] + prefix + str(c["resume_anchor"])], c)


@pytest.mark.parametrize("suffix", ["的计划尚待批准。", "的安排仍未确定。"])
def test_planned_suffix_cannot_be_removed_from_anchor(suffix: str) -> None:
    c = claim()
    c["resume_anchor"] = "公司股票2017年8月22日开市起复牌"
    with pytest.raises(ValueError, match="sentence ending"):
        verify_notice_text([pages()[0] + str(c["resume_anchor"]) + suffix], c)


def test_cross_notice_start_requires_same_issuer_and_security() -> None:
    c = claim() | {"issuer_name": "测试发行人"}
    primary = ["测试发行人\n证券代码:000001\n" + str(c["resume_anchor"])]
    start = ["测试发行人\n证券代码:000001\n" + str(c["start_anchor"])]
    assert verify_notice_text(primary, c, start_pages=start)[0] == date(2017, 8, 19)
    with pytest.raises(ValueError, match="start issuer"):
        verify_notice_text(primary, c, start_pages=[start[0].replace("测试发行人", "其他发行人")])
    with pytest.raises(ValueError, match="security code"):
        verify_notice_text(primary, c, start_pages=[start[0].replace("000001", "000002")])


def test_numbered_list_resumption_clause() -> None:
    c = claim()
    c["resume_anchor"] = "公司股票于2017年8月22日开市起复牌;"
    text = "证券代码:000001。" + str(c["start_anchor"]) + str(c["resume_anchor"])
    assert verify_notice_text([text + "2、其他事项。"], c)[1] == date(2017, 8, 21)
    with pytest.raises(ValueError, match="numbered list"):
        verify_notice_text([text + "上述安排尚待批准。"], c)


def test_start_pdf_hash_and_official_url(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    manifest = notice_manifest(tmp_path, monkeypatch)
    c = json.loads(manifest.read_bytes())["claims"][0]
    raw = b"%PDF-start-fixture"
    digest = sha256(raw).hexdigest()
    (tmp_path / (digest + ".pdf")).write_bytes(raw)
    c.update(
        issuer_name="测试发行人", start_raw_sha256=digest, start_official_url=c["official_url"]
    )
    text = "测试发行人" + pages()[0]
    monkeypatch.setattr(
        "quant_stack_v2.szse_issuer_supplement.subprocess.run",
        lambda *a, **k: subprocess.CompletedProcess([], 0, stdout=text.encode()),
    )
    manifest = hashed(tmp_path, {"claims": [c]})
    assert (
        load_claims(manifest)[0][0]["start_extracted_text_sha256"]
        == sha256(text.encode()).hexdigest()
    )
    (tmp_path / (digest + ".pdf")).write_bytes(b"tamper")
    with pytest.raises(ValueError, match="start PDF SHA"):
        load_claims(manifest)
    c["start_official_url"] = "https://example.invalid/not-official.pdf"
    with pytest.raises(ValueError, match="non-official"):
        load_claims(hashed(tmp_path, {"claims": [c]}))


def test_reporting_intro_is_not_future_resumption() -> None:
    c = claim()
    c["resume_anchor"] = "公司股票于2017年8月22日开市起复牌;"
    base = "证券代码:000001。" + str(c["start_anchor"]) + "现将有关核查情况说明如下:1、"
    assert verify_notice_text([base + str(c["resume_anchor"]) + "2、其他事项。"], c)[1] == date(
        2017, 8, 21
    )
    with pytest.raises(ValueError, match="sentence context"):
        verify_notice_text([base + "拟申请" + str(c["resume_anchor"]) + "2、其他事项。"], c)


@pytest.mark.parametrize(
    "anchor",
    [
        "公司股票自2017年8月22日开市起复牌。",
        "公司股票于2017年8月22日开市起复牌并可在股票复牌后继续推进资产收购事项。",
    ],
)
def test_additional_reviewed_past_tense_clauses(anchor: str) -> None:
    c = claim()
    c["resume_anchor"] = anchor
    assert verify_notice_text([pages()[0] + anchor], c)[1] == date(2017, 8, 21)
    with pytest.raises(ValueError, match="sentence context"):
        verify_notice_text([pages()[0] + "计划安排" + anchor], c)


def test_security_parenthesis_and_completed_disclosure() -> None:
    c = claim() | {"security_name": "测试证券"}
    anchor = "公司股票(证券简称:测试证券,证券代码:000001)自2017年8月22日开市起复牌,"
    c["resume_anchor"] = anchor
    base = pages()[0] + anchor
    assert verify_notice_text([base + "并于2017年8月22日披露了复牌公告。"], c)[1] == date(
        2017, 8, 21
    )
    with pytest.raises(ValueError, match="completed disclosure"):
        verify_notice_text([base + "但计划尚待批准。"], c)
    c["security_name"] = "其他证券"
    with pytest.raises(ValueError, match="actual resumption"):
        verify_notice_text([base + "并于2017年8月22日披露了复牌公告。"], c)


@pytest.mark.parametrize("publication", ["2017-08-21", "2017-08-22"])
def test_same_day_arrangement_is_not_retrospective(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, publication: str
) -> None:
    manifest = notice_manifest(tmp_path, monkeypatch)
    payload = json.loads(manifest.read_bytes())
    payload["claims"][0]["official_url"] = (
        f"https://static.cninfo.com.cn/finalpage/{publication}/example.PDF"
    )
    with pytest.raises(ValueError, match="published after"):
        load_claims(hashed(tmp_path, payload))


@pytest.mark.parametrize("title,code", [("复牌公告(已取消)", "000001"), ("复牌公告", "000002")])
def test_catalogue_rejects_withdrawal_or_wrong_security(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, title: str, code: str
) -> None:
    manifest = notice_manifest(tmp_path, monkeypatch)
    payload = json.loads(manifest.read_bytes())
    body = json.dumps(
        {
            "announcements": [
                {
                    "secCode": code,
                    "announcementTitle": title,
                    "adjunctUrl": "finalpage/2017-08-30/example.PDF",
                }
            ]
        }
    ).encode()
    digest = sha256(body).hexdigest()
    (tmp_path / (digest + ".catalog.json")).write_bytes(body)
    payload["claims"][0]["catalog_raw_sha256"] = digest
    with pytest.raises(ValueError, match=r"withdrawn|binding"):
        load_claims(hashed(tmp_path, payload))


def test_completed_trading_and_simultaneous_disclosure() -> None:
    c = claim()
    c["resume_anchor"] = "公司股票于2017年8月22日开市起复牌交易。"
    assert verify_notice_text([pages()[0] + str(c["resume_anchor"])], c)[1] == date(2017, 8, 21)
    c["resume_anchor"] = "公司股票于2017年8月22日开市起复牌,"
    base = pages()[0] + str(c["resume_anchor"])
    assert verify_notice_text([base + "公司同步在网上披露了修订稿。"], c)[1] == date(2017, 8, 21)
    with pytest.raises(ValueError, match="completed disclosure"):
        verify_notice_text([base + "公司拟同步在网上披露修订稿。"], c)


def test_failed_negotiations_are_not_failed_resumption() -> None:
    c = claim()
    base = pages()[0].split("公司股票于2017年8月22日")[0]
    prefix = "后鉴于与交易对方就交易核心条款未能达成一致意见,公司决定终止重组,"
    assert verify_notice_text([base + prefix + str(c["resume_anchor"])], c)[1] == date(2017, 8, 21)
    with pytest.raises(ValueError, match="sentence context"):
        verify_notice_text([base + prefix + "计划" + str(c["resume_anchor"])], c)
