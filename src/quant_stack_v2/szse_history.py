"""Reviewed, publication-bounded issuer suspension histories; never actual resumptions."""

from __future__ import annotations

import json
import re
import subprocess
from datetime import date, datetime, timedelta, timezone
from hashlib import sha256
from pathlib import Path
from typing import Any

from quant_stack_v2.szse_issuer_supplement import _chinese_date, _compact
from quant_stack_v2.szse_monthly import load_months

MONTHLY_INDEX = (
    Path(__file__).resolve().parents[2]
    / "artifacts/v2/szse_monthly_evidence"
    / "2140ec9a8ca8e17a542a7d8337ed3d672f655c86acf3446d82d8bc691b662ac1.json"
)


def _signed_matches(anchor: str, value: date) -> bool:
    digits = "零一二三四五六七八九"

    def number(n: int) -> str:
        return (
            digits[n]
            if n < 10
            else (digits[n // 10] if n >= 20 else "") + "十" + (digits[n % 10] if n % 10 else "")
        )

    chinese = (
        "".join(digits[int(d)] for d in str(value.year))
        + "年"
        + number(value.month)
        + "月"
        + number(value.day)
        + "日"
    )
    normalized = _compact(anchor)
    if _chinese_date(value) in normalized:
        return True
    normalized = normalized.translate(str.maketrans("\u3007\u25cbO\u039f0", "零零零零零"))
    return chinese in normalized


def _explicit_continuing_state(anchor: str) -> bool:
    normalized = _compact(anchor)
    return (
        re.search(
            r"(?:公司|本公司)(?:A股)?股票[^。\uff1b;!?]{0,120}(?:继续|连续)停牌"
            r"|(?:公司|本公司)(?:A股)?股票(?:交易)?(?:仍(?:处于)?停牌(?:状态)?|尚未复牌)",
            normalized,
        )
        is not None
    )


def _has_completed_resume_in_window(pages: list[str], start: date, cutoff: date) -> bool:
    text = _compact("".join(pages))
    pattern = re.compile(
        r"(?:公司|本公司)(?:A股)?股票(?:\([^)]{1,80}\))?(?:已于|于|自)"
        r"(?P<year>\d{4})年(?P<month>\d{1,2})月(?P<day>\d{1,2})日"
        r"(?:(?:上午|下午)?开市起|(?:上午|下午)?开市|起)?"
        r"(?:已)?(?:复牌(?:交易)?|恢复交易)"
    )
    for match in pattern.finditer(text):
        resumed = date(int(match["year"]), int(match["month"]), int(match["day"]))
        if start < resumed < cutoff:
            return True
    return False


def _read(root: Path, digest: str, suffix: str) -> bytes:
    if re.fullmatch(r"[a-f0-9]{64}", digest) is None:
        raise ValueError("invalid history evidence hash")
    body = (root / (digest + suffix)).read_bytes()
    if sha256(body).hexdigest() != digest:
        raise ValueError("history evidence SHA mismatch")
    return body


def load_histories(path: Path) -> list[dict[str, Any]]:
    """Recheck reviewed same-event excerpts against hashed official catalog and PDF."""
    body = _read(path.parent, path.stem, ".json")
    manifest = json.loads(body)
    if manifest["scope"] != "REVIEWED_DATED_SUSPENSION_HISTORY":
        raise ValueError("unexpected history scope")
    monthly_events = load_months(MONTHLY_INDEX)
    verified = []
    for claim in manifest["claims"]:
        catalog = json.loads(_read(path.parent, claim["catalog_sha256"], ".catalog.json"))
        matches = [
            r
            for r in catalog["announcements"]
            if str(r["announcementId"]) == claim["announcement_id"]
        ]
        if len(matches) != 1:
            raise ValueError("history catalog announcement mismatch")
        row = matches[0]
        if (
            "sz" + row["secCode"] != claim["symbol"]
            or re.search(r"取消|撤回|作废", row["announcementTitle"])
            or "https://static.cninfo.com.cn/" + row["adjunctUrl"] != claim["official_url"]
        ):
            raise ValueError("history catalog identity or validity mismatch")
        published = date.fromisoformat(row["adjunctUrl"].split("/")[1])
        timestamp_day = datetime.fromtimestamp(
            row["announcementTime"] / 1000, timezone(timedelta(hours=8))
        ).date()
        if timestamp_day != published:
            raise ValueError("history catalog publication date mismatch")
        start = date.fromisoformat(claim["start_date"])
        signed = date.fromisoformat(claim["signed_date"])
        cutoff = date.fromisoformat(claim["evidence_cutoff_exclusive"])
        planned = (
            date.fromisoformat(claim["planned_resume_date"])
            if claim.get("planned_resume_date") is not None
            else None
        )
        upper_bound = min(published, signed + timedelta(days=1), *([planned] if planned else []))
        if not start < cutoff <= upper_bound:
            raise ValueError("history cutoff exceeds observed state")
        if planned is None:
            if claim.get("evidence_kind") != "CONTINUING_SUSPENSION_STATE":
                raise ValueError("unplanned history must be a continuing-state record")
            if cutoff != upper_bound:
                raise ValueError("continuing-state history must end at observed boundary")
        if any(
            e.symbol == claim["symbol"]
            and (
                start < e.start.date() < cutoff
                or (e.resume is not None and start < e.resume.date() < cutoff)
            )
            for e in monthly_events
        ):
            raise ValueError("history conflicts with monthly actual resumption")
        if claim["actual_resume_date"] is not None or claim["closed_actual"] is not False:
            raise ValueError("history cannot assert actual resumption")
        if claim["right_censored"] is not True:
            raise ValueError("history must be right censored")
        _read(path.parent, claim["raw_sha256"], ".pdf")
        raw = subprocess.run(
            [
                "/usr/bin/pdftotext",
                "-layout",
                str(path.parent / (claim["raw_sha256"] + ".pdf")),
                "-",
            ],
            capture_output=True,
            check=True,
            timeout=30,
        ).stdout
        pages = [_compact(p) for p in raw.decode().split("\f")]
        if (
            _compact(claim["issuer_name"]) not in pages[0]
            or re.search(
                r"(?:证券|股票)代码(?:\(A/H\))?:?" + claim["symbol"][2:] + r"(?!\d)", pages[0]
            )
            is None
        ):
            raise ValueError("history visible issuer identity mismatch")
        for key in ("start", "continuity", "signed") + (("planned",) if planned else ()):
            if key == "planned" and "planned_fragments" in claim:
                fragments = claim["planned_fragments"]
                if len(fragments) != 2 or fragments[1]["page"] != fragments[0]["page"] + 1:
                    raise ValueError("planned fragments must span adjacent pages")
                if claim["planned_page"] != fragments[0]["page"]:
                    raise ValueError("planned page must match first fragment")
                if any(not _compact(fragment["anchor"]) for fragment in fragments):
                    raise ValueError("planned fragment anchors must be non-empty")
                for fragment in fragments:
                    if (
                        not 1 <= fragment["page"] <= len(pages)
                        or _compact(fragment["anchor"]) not in pages[fragment["page"] - 1]
                    ):
                        raise ValueError("planned fragment missing")
                if _compact(claim["planned_anchor"]) != "".join(
                    _compact(f["anchor"]) for f in fragments
                ):
                    raise ValueError("planned fragment join mismatch")
                first, second = fragments
                first_text = pages[first["page"] - 1]
                anchor = _compact(first["anchor"])
                if first_text.count(anchor) != 1 or first_text.split(anchor)[-1] not in (
                    "",
                    str(first["page"]),
                ):
                    raise ValueError("first planned fragment must end page body")
                if not pages[second["page"] - 1].startswith(_compact(second["anchor"])):
                    raise ValueError("second planned fragment must start page body")
                continue
            page = claim[key + "_page"]
            anchor = _compact(claim[key + "_anchor"])
            if not 1 <= page <= len(pages) or not anchor or anchor not in pages[page - 1]:
                raise ValueError("history excerpt missing from stated page")
        if not _signed_matches(claim["signed_anchor"], signed):
            raise ValueError("history signed date mismatch")
        if (
            _chinese_date(start) not in _compact(claim["start_anchor"])
            or "停牌" not in claim["start_anchor"]
        ):
            raise ValueError("history start anchor mismatch")
        bounded_pair = claim.get("evidence_kind") == "BOUNDED_START_TO_PLANNED_BOUNDARY"
        if bounded_pair:
            context = _compact(claim["continuity_anchor"])
            if (
                planned is None
                or cutoff != upper_bound
                or "复牌" not in row["announcementTitle"]
                or not claim["start_page"] == claim["planned_page"] == claim["continuity_page"]
                or _compact(claim["start_anchor"]) not in context
                or _compact(claim["planned_anchor"]) not in context
                or "公司股票" not in _compact(claim["start_anchor"])
                or "公司股票" not in _compact(claim["planned_anchor"])
            ):
                raise ValueError(
                    "bounded pair requires same-notice issuer start and dated boundary"
                )
            if _has_completed_resume_in_window(pages, start, cutoff):
                raise ValueError("bounded pair conflicts with completed resumption")
        elif not re.search(
            r"停牌期间|继续停牌|连续停牌|停牌以来|停牌后|停牌至今|停牌进展公告",
            claim["continuity_anchor"],
        ):
            raise ValueError("history continuity review required")
        if planned is None:
            if not _explicit_continuing_state(claim["continuity_anchor"]):
                raise ValueError("continuing-state history requires explicit current suspension")
            if _has_completed_resume_in_window(pages, start, cutoff):
                raise ValueError("continuing-state history conflicts with completed resumption")
        if planned and (
            _chinese_date(planned) not in _compact(claim["planned_anchor"])
            or "复牌" not in claim["planned_anchor"]
        ):
            raise ValueError("history planned-date anchor mismatch")
        verified.append(claim | {"extracted_text_sha256": sha256(raw).hexdigest()})
    return verified


def apply_histories(
    rows: list[list[str]], histories: list[dict[str, Any]], actual_claims: list[dict[str, Any]]
) -> tuple[list[list[str]], list[dict[str, Any]]]:
    """Explain only unknown days, with no extension to cutoff or planned resumption."""
    output = []
    changes = []
    for symbol, session, label in rows:
        matching = [
            h
            for h in histories
            if h["symbol"] == symbol and h["start_date"] < session < h["evidence_cutoff_exclusive"]
        ]
        contradictory = any(
            c["symbol"] == symbol
            and h["start_date"] < c["resume_date"] < h["evidence_cutoff_exclusive"]
            for h in matching
            for c in actual_claims
        )
        if label == "UNEXPLAINED" and matching and not contradictory:
            label = "ISSUER_CONFIRMED_HISTORY"
            changes.append({"symbol": symbol, "session": session, "evidence": matching})
        output.append([symbol, session, label])
    return output, changes
