"""Offline, retrospective issuer-notice supplementation of SZSE missing sessions."""

from __future__ import annotations

import argparse
import copy
import json
import re
import subprocess
import unicodedata
from collections import Counter
from datetime import date, timedelta
from hashlib import sha256
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from quant_stack_v2.szse_verification import persist_report


def _compact(value: str) -> str:
    return re.sub(r"\s+", "", unicodedata.normalize("NFKC", value))


def _chinese_date(value: date) -> str:
    return f"{value.year}年{value.month}月{value.day}日"


def verify_notice_text(
    pages: list[str],
    claim: dict[str, Any],
    identity_pages: list[str] | None = None,
    start_pages: list[str] | None = None,
) -> tuple[date, date]:
    """Verify reviewed issuer/date anchors; reject planned or open-ended resumptions."""
    symbol = claim["symbol"]
    if re.fullmatch(r"sz\d{6}", symbol) is None:
        raise ValueError("invalid SZ issuer identity")
    identity = identity_pages if identity_pages is not None else pages
    text = _compact("".join(identity))
    if identity_pages is not None:
        issuer = _compact(claim["issuer_name"])
        if not issuer or issuer not in _compact(pages[0]) or issuer not in _compact(identity[0]):
            raise ValueError("cross-notice issuer identity mismatch")
    if re.search(r"(?:证券|股票)代码:?" + symbol[2:] + r"(?!\d)", text) is None:
        raise ValueError("issuer security code missing")
    start, resume = (
        date.fromisoformat(claim["start_date"]),
        date.fromisoformat(claim["resume_date"]),
    )
    if resume <= start or resume.year == 9999:
        raise ValueError("invalid closed notice interval")
    if start_pages is not None:
        issuer = _compact(claim["issuer_name"])
        if not issuer or issuer not in _compact(pages[0]) or issuer not in _compact(start_pages[0]):
            raise ValueError("cross-notice start issuer mismatch")
        if (
            re.search(
                r"(?:证券|股票)代码:?" + symbol[2:] + r"(?!\d)", _compact("".join(start_pages))
            )
            is None
        ):
            raise ValueError("start notice security code missing")
    for key in ("start", "resume"):
        source_pages = start_pages if key == "start" and start_pages is not None else pages
        page = claim[key + "_page"]
        if not isinstance(page, int) or not 1 <= page <= len(source_pages):
            raise ValueError("invalid notice page")
        anchor = _compact(claim[key + "_anchor"])
        if not anchor or anchor not in _compact(source_pages[page - 1]):
            raise ValueError("notice anchor missing from stated page")
    start_anchor, resume_anchor = _compact(claim["start_anchor"]), _compact(claim["resume_anchor"])
    if not resume_anchor.endswith(("。", ".", ";", ",")):
        raise ValueError("resumption anchor must include the sentence ending")
    resume_page = _compact(pages[claim["resume_page"] - 1])
    if resume_page.count(resume_anchor) != 1:
        raise ValueError("ambiguous resumption anchor")
    if resume_anchor.endswith(";"):
        tail = resume_page[resume_page.index(resume_anchor) + len(resume_anchor) :]
        if re.match(r"\d+[、.)]", tail) is None:
            raise ValueError("semicolon resumption must end a numbered list item")
    if resume_anchor.endswith(","):
        tail = resume_page[resume_page.index(resume_anchor) + len(resume_anchor) :]
        if not (
            tail.startswith("并于" + _chinese_date(resume) + "披露了")
            or tail.startswith("公司同步在网上披露了")
        ):
            raise ValueError("comma resumption must precede same-day completed disclosure")
    prefix = resume_page[: resume_page.index(resume_anchor)]
    sentence_prefix = re.split(r"[。!?]", prefix)[-1]
    sentence_prefix = sentence_prefix.replace("现将有关核查情况说明如下:", "")
    sentence_prefix = sentence_prefix.replace("与交易对方就交易核心条款未能达成一致意见", "")
    if re.search(
        r"拟|将|预计|计划|不晚于|最晚|假设|如果|若|尚未|未能|不会|不能|并未", sentence_prefix
    ):
        raise ValueError("actual resumption requires non-planned sentence context")
    if _chinese_date(start) not in start_anchor or "停牌" not in start_anchor:
        raise ValueError("start date anchor mismatch")
    security_clause = ""
    if "security_name" in claim:
        security_clause = (
            r"(?:\(证券简称:"
            + re.escape(_compact(claim["security_name"]))
            + ",证券代码:"
            + symbol[2:]
            + r"\))?"
        )
    # The anchor must include the subject immediately before the completed-action wording.
    if (
        re.fullmatch(
            r"(?:公司|本公司)?(?:A股)?股票"
            + security_clause
            + r"(?:已)?"
            + r"(?:(?:于|自)"
            + re.escape(_chinese_date(start))
            + r"(?:起|开市起)?停牌,)?"
            + r"(?:于|自)?"
            + re.escape(_chinese_date(resume))
            + r"(?:开市起|开市|起)?(?:复牌(?:交易)?|恢复交易)"
            + r"(?:并可在股票复牌后继续推进资产收购事项)?[。.;,]?",
            resume_anchor,
        )
        is None
    ):
        raise ValueError("actual resumption statement required; plans are not evidence")
    # Start-day timing is not inferred from a date alone. Existing monthly evidence stays intact.
    return start + timedelta(days=1), resume - timedelta(days=1)


def load_claims(manifest_path: Path) -> tuple[list[dict[str, Any]], str]:
    """Hash-check source PDFs and independently re-extract the reviewed anchors offline."""
    body = manifest_path.read_bytes()
    digest = sha256(body).hexdigest()
    if manifest_path.stem != digest:
        raise ValueError("notice manifest SHA-256 mismatch")
    manifest = json.loads(body)
    claims: list[dict[str, Any]] = []
    for claim in manifest["claims"]:
        raw_hash = claim["raw_sha256"]
        if re.fullmatch(r"[a-f0-9]{64}", raw_hash) is None:
            raise ValueError("invalid PDF identity")
        url_fields = ["official_url"]
        if "identity_raw_sha256" in claim:
            url_fields.append("identity_official_url")
        if "start_raw_sha256" in claim:
            url_fields.append("start_official_url")
        for field in url_fields:
            url = urlparse(claim[field])
            if url.scheme != "https" or url.hostname not in (
                "static.cninfo.com.cn",
                "disc.static.szse.cn",
                "www.szse.cn",
                "docs.static.szse.cn",
            ):
                raise ValueError("non-official issuer notice URL")
        if "catalog_raw_sha256" in claim:
            catalog_hash = claim["catalog_raw_sha256"]
            if re.fullmatch(r"[a-f0-9]{64}", catalog_hash) is None:
                raise ValueError("invalid catalog hash")
            catalog_body = (manifest_path.parent / (catalog_hash + ".catalog.json")).read_bytes()
            if sha256(catalog_body).hexdigest() != catalog_hash:
                raise ValueError("catalog SHA-256 mismatch")
            catalog_rows = json.loads(catalog_body)["announcements"]
            selected = [
                r for r in catalog_rows if claim["official_url"].endswith("/" + r["adjunctUrl"])
            ]
            if len(selected) != 1 or selected[0]["secCode"] != claim["symbol"][2:]:
                raise ValueError("catalog notice/security binding mismatch")
            if "已取消" in selected[0]["announcementTitle"]:
                raise ValueError("withdrawn notice is not admissible")
        publication_match = re.search(
            r"/finalpage/(\d{4}-\d{2}-\d{2})/", urlparse(claim["official_url"]).path
        )
        if publication_match is None:
            raise ValueError("dated official notice URL required")
        publication_date = date.fromisoformat(publication_match[1])
        if publication_date <= date.fromisoformat(claim["resume_date"]):
            raise ValueError("retrospective notice must be published after actual resumption date")
        pdf = manifest_path.parent / (raw_hash + ".pdf")
        if sha256(pdf.read_bytes()).hexdigest() != raw_hash:
            raise ValueError("notice PDF SHA-256 mismatch")
        extracted = subprocess.run(
            ["/usr/bin/pdftotext", "-layout", str(pdf), "-"],
            check=True,
            capture_output=True,
            timeout=30,
        ).stdout.decode("utf-8")
        identity_pages = None
        if "identity_raw_sha256" in claim:
            identity_hash = claim["identity_raw_sha256"]
            if re.fullmatch(r"[a-f0-9]{64}", identity_hash) is None:
                raise ValueError("invalid identity PDF hash")
            identity_pdf = manifest_path.parent / (identity_hash + ".pdf")
            if sha256(identity_pdf.read_bytes()).hexdigest() != identity_hash:
                raise ValueError("identity PDF SHA-256 mismatch")
            identity_text = subprocess.run(
                ["/usr/bin/pdftotext", "-layout", str(identity_pdf), "-"],
                check=True,
                capture_output=True,
                timeout=30,
            ).stdout.decode("utf-8")
            identity_pages = identity_text.split("\f")
        start_pages = None
        start_text_hash = None
        if "start_raw_sha256" in claim:
            start_hash = claim["start_raw_sha256"]
            if re.fullmatch(r"[a-f0-9]{64}", start_hash) is None:
                raise ValueError("invalid start PDF hash")
            start_pdf = manifest_path.parent / (start_hash + ".pdf")
            if sha256(start_pdf.read_bytes()).hexdigest() != start_hash:
                raise ValueError("start PDF SHA-256 mismatch")
            start_text = subprocess.run(
                ["/usr/bin/pdftotext", "-layout", str(start_pdf), "-"],
                check=True,
                capture_output=True,
                timeout=30,
            ).stdout.decode("utf-8")
            start_pages = start_text.split("\f")
            start_text_hash = sha256(start_text.encode()).hexdigest()
        first, last = verify_notice_text(extracted.split("\f"), claim, identity_pages, start_pages)
        claims.append(
            {
                **claim,
                **({"start_extracted_text_sha256": start_text_hash} if start_text_hash else {}),
                "first_full_session": first.isoformat(),
                "last_full_session": last.isoformat(),
                "extracted_text_sha256": sha256(extracted.encode()).hexdigest(),
            }
        )
    if not claims:
        raise ValueError("empty supplement manifest")
    return claims, digest


def supplement(report_path: Path, manifest_path: Path) -> dict[str, Any]:
    """Add verified issuer evidence without overriding conflicts or membership qualification."""
    body = report_path.read_bytes()
    digest = sha256(body).hexdigest()
    if report_path.stem != digest:
        raise ValueError("source report SHA-256 mismatch")
    original = json.loads(body)
    if original["scope"] != "SZSE_MISSING_SESSIONS_ONLY_RETROSPECTIVE":
        raise ValueError("unexpected source report scope")
    claims, manifest_digest = load_claims(manifest_path)
    results = copy.deepcopy(original["results"])
    new_counts: Counter[str] = Counter()
    conflicts: list[dict[str, str]] = []
    all_dates: set[tuple[str, str]] = set()
    residual: list[dict[str, Any]] = []
    counts: Counter[str] = Counter()
    for result in results:
        symbol = result["task"]["symbol"]
        for row in result["dates"]:
            key = (symbol, row["session"])
            if key in all_dates:
                raise ValueError("duplicate source date")
            all_dates.add(key)
            matching = [
                c
                for c in claims
                if c["symbol"] == symbol
                and c["first_full_session"] <= row["session"] <= c["last_full_session"]
            ]
            resume_day = any(
                c["symbol"] == symbol and c["resume_date"] == row["session"] for c in claims
            )
            incompatible = any(
                a["symbol"] == symbol
                and b["symbol"] == symbol
                and a["start_date"] == b["start_date"]
                and a["resume_date"] != b["resume_date"]
                and a["start_date"] <= row["session"] <= max(a["resume_date"], b["resume_date"])
                for a in claims
                for b in claims
            )
            if resume_day or incompatible:
                conflicts.append(
                    {
                        "symbol": symbol,
                        "session": row["session"],
                        "reason": "NOTICE_RESUMPTION_CONFLICT",
                    }
                )
                row["classification"] = "CONFLICT"
                row["reason"] = "NOTICE_RESUMPTION_CONFLICT"
                row["evidence"] = row["evidence"] + [c for c in claims if c["symbol"] == symbol]
            elif row["classification"] == "UNEXPLAINED" and matching:
                row["classification"] = "ISSUER_CONFIRMED_SUSPENDED"
                row["reason"] = "RETROSPECTIVE_ISSUER_NOTICE"
                row["evidence"] = matching
                new_counts[symbol] += 1
            if row["classification"] not in ("OFFICIAL_SUSPENDED", "ISSUER_CONFIRMED_SUSPENDED"):
                residual.append({"symbol": symbol, **row})
            counts[row["classification"]] += 1
        day_counts = Counter(r["classification"] for r in result["dates"])
        covered = day_counts["OFFICIAL_SUSPENDED"] + day_counts["ISSUER_CONFIRMED_SUSPENDED"]
        result["daily_counts"] = dict(day_counts)
        result["status"] = (
            "CONFLICT"
            if day_counts["CONFLICT"]
            else "FULL"
            if covered == len(result["dates"])
            else "PARTIAL"
            if covered
            else "NO_MATCH"
        )
    if len(all_dates) != original["missing_sessions"]:
        raise ValueError("source missing-session count mismatch")
    remaining_tasks = []
    for result in results:
        remaining = [
            r["session"]
            for r in result["dates"]
            if r["classification"] not in ("OFFICIAL_SUSPENDED", "ISSUER_CONFIRMED_SUSPENDED")
        ]
        if remaining:
            remaining_tasks.append(
                {
                    "symbol": result["task"]["symbol"],
                    "candidate_start": result["task"]["start_session"],
                    "candidate_end": result["task"]["end_session"],
                    "remaining_first": min(remaining),
                    "remaining_last": max(remaining),
                    "remaining_session_count": len(remaining),
                }
            )
    return {
        "schema_version": 1,
        "scope": "SZSE_MONTHLY_PLUS_ISSUER_NOTICES_RETROSPECTIVE",
        "source_report_sha256": digest,
        "manifest_sha256": manifest_digest,
        "supplement_source_sha256": sha256(Path(__file__).read_bytes()).hexdigest(),
        "original_input_sha256": {
            key: original[key] for key in ("index_sha256", "plan_sha256", "audit_sha256")
        },
        "original_source_sha256": original["source_sha256"],
        "source_missing_sessions": original["missing_sessions"],
        "original_covered_sessions": original["covered_sessions"],
        "original_uncovered_sessions": original["uncovered_sessions"],
        "newly_explained_sessions": sum(new_counts.values()),
        "newly_explained_by_symbol": dict(sorted(new_counts.items())),
        "covered_sessions": counts["OFFICIAL_SUSPENDED"] + counts["ISSUER_CONFIRMED_SUSPENDED"],
        "uncovered_sessions": len(residual),
        "conflict_sessions": counts["CONFLICT"],
        "interval_counts": {
            status: sum(r["status"] == status for r in results)
            for status in ("FULL", "PARTIAL", "NO_MATCH", "CONFLICT")
        },
        "gap_gate": "PASS" if not residual else "BLOCKED_DATA",
        "membership_gate": original["membership_gate"],
        "top_residual_tasks": sorted(
            remaining_tasks,
            key=lambda t: (
                -int(t["remaining_session_count"]),
                str(t["symbol"]),
                str(t["candidate_start"]),
            ),
        )[:20],
        "claims": claims,
        "notice_conflicts": conflicts,
        "results": results,
        "residual": residual,
    }


def main() -> None:
    """Run the fixed offline supplement and retain a new immutable sealed report."""
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("report", "manifest", "output-root"):
        parser.add_argument("--" + name, type=Path, required=True)
    parser.add_argument("--all-residual-tasks", action="store_true")
    args = parser.parse_args()
    result = supplement(args.report, args.manifest)
    path = persist_report(result, args.output_root)
    summary = {
        k: v
        for k, v in result.items()
        if k not in ("claims", "notice_conflicts", "results", "residual")
    } | {"report_path": str(path)}
    if args.all_residual_tasks:
        from quant_stack_v2.szse_evidence_queue import build_queue

        summary["residual_evidence_queue"] = build_queue(path)
    print(json.dumps(summary))
    raise SystemExit(0 if result["gap_gate"] == "PASS" else 1)


if __name__ == "__main__":
    main()
