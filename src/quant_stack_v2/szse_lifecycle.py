"""Official terminal-listing evidence, independent of suspension and PIT membership."""

from __future__ import annotations

import json
import re
import subprocess
from datetime import date
from pathlib import Path
from typing import Any

from quant_stack_v2.szse_history import _read
from quant_stack_v2.szse_issuer_supplement import _chinese_date, _compact


def load_delistings(path: Path) -> list[dict[str, Any]]:
    """Verify official issuer delisting decisions against immutable catalog/PDF anchors."""
    manifest = json.loads(_read(path.parent, path.stem, ".json"))
    if manifest["scope"] != "SZSE_OFFICIAL_DELISTING_DECISIONS_NOT_PIT":
        raise ValueError("unexpected lifecycle evidence scope")
    for claim in manifest["claims"]:
        if claim["source_kind"] != "ISSUER_NOTICE_REPORTING_EXCHANGE_DECISION":
            raise ValueError("delisting source kind mismatch")
        catalog = json.loads(_read(path.parent, claim["catalog_sha256"], ".catalog.json"))
        selected = [
            r
            for r in catalog["announcements"]
            if str(r["announcementId"]) == claim["announcement_id"]
        ]
        if len(selected) != 1:
            raise ValueError("delisting catalog identity mismatch")
        row = selected[0]
        if (
            "sz" + row["secCode"] != claim["symbol"]
            or "https://static.cninfo.com.cn/" + row["adjunctUrl"] != claim["official_url"]
            or re.search(r"取消|撤回|作废", row["announcementTitle"])
        ):
            raise ValueError("delisting catalog identity or validity mismatch")
        effective = date.fromisoformat(claim["effective_date"])
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
        ).stdout.decode()
        pages = [_compact(p) for p in raw.split("\f")]
        if (
            _compact(claim["issuer_name"]) not in pages[0]
            or re.search(r"证券代码:?" + claim["symbol"][2:] + r"(?!\d)", pages[0]) is None
        ):
            raise ValueError("delisting visible issuer mismatch")
        anchor = _compact(claim["effective_anchor"])
        if (
            not 1 <= claim["effective_page"] <= len(pages)
            or anchor not in pages[claim["effective_page"] - 1]
        ):
            raise ValueError("delisting effective anchor missing")
        if anchor != "终止上市日期:" + _chinese_date(effective) + "。":
            raise ValueError("explicit delisting effective date required")
        decision = _compact(claim["decision_anchor"])
        if (
            decision not in pages[claim["effective_page"] - 1]
            or "深圳证券交易所" not in decision
            or "已同意" not in decision
            or "终止上市并摘牌" not in decision
            or _chinese_date(effective) not in decision
        ):
            raise ValueError("exchange delisting approval required")
    return list(manifest["claims"])


def apply_delistings(rows: list[list[str]], claims: list[dict[str, Any]]) -> list[list[str]]:
    """Retain member dates and conflicts; identify sessions on/after official delisting."""
    return [
        [
            symbol,
            session,
            "POST_DELISTING"
            if label != "CONFLICT"
            and any(c["symbol"] == symbol and session >= c["effective_date"] for c in claims)
            else label,
        ]
        for symbol, session, label in rows
    ]
