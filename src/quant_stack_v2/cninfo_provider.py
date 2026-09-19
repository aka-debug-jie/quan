"""Bounded official CNINFO announcement discovery for EXQ-001."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from hashlib import sha256
from pathlib import Path
from typing import Any
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from quant_stack.snapshot import write_immutable
from quant_stack_v2.dev_contract import canonical

STOCK_URL = "https://www.cninfo.com.cn/new/data/szse_stock.json"
QUERY_URL = "https://www.cninfo.com.cn/new/hisAnnouncement/query"
PDF_BASE = "https://static.cninfo.com.cn/"
HEADERS = {
    "User-Agent": "quant-stack-v2/1.0",
    "X-Requested-With": "XMLHttpRequest",
    "Referer": "https://www.cninfo.com.cn/new/commonUrl/pageOfSearch?url=disclosure/list/search",
}


def discover(
    data_root: Path, symbol: str, start: str, end: str, *, allow_network: bool
) -> dict[str, object]:
    """Archive one official announcement catalog for one exact symbol/date window."""
    if not allow_network or not symbol.startswith("sz"):
        raise ValueError("CNINFO discovery requires network and an SZ symbol")
    stocks = _get(STOCK_URL)
    mapping = {item["code"]: item["orgId"] for item in json.loads(stocks)["stockList"]}
    code = symbol[2:]
    if code not in mapping:
        raise ValueError("CNINFO stock mapping lacks symbol")
    stock_sha = sha256(stocks).hexdigest()
    write_immutable(data_root / "cninfo_stock_maps" / (stock_sha + ".json"), stocks)
    parameters = {
        "pageNum": "1",
        "pageSize": "30",
        "column": "szse",
        "tabName": "fulltext",
        "plate": "",
        "stock": f"{code},{mapping[code]}",
        "searchkey": "",
        "secid": "",
        "category": "",
        "trade": "",
        "seDate": f"{start}~{end}",
        "sortName": "",
        "sortType": "",
        "isHLtitle": "true",
    }
    announcements: list[dict[str, Any]] = []
    pages: list[str] = []
    seen: set[str] = set()
    expected_total: int | None = None
    for page_number in range(1, 101):
        parameters["pageNum"] = str(page_number)
        raw = _post(QUERY_URL, urlencode(parameters).encode())
        digest = sha256(raw).hexdigest()
        base = data_root / "cninfo_catalogs" / digest
        write_immutable(base / "response.json", raw)
        receipt = canonical(
            {
                "symbol": symbol,
                "request": parameters,
                "source_url": QUERY_URL,
                "raw_sha256": digest,
                "stock_map_sha256": stock_sha,
                "retrieved_at_utc": datetime.now(UTC).isoformat(),
            }
        )
        write_immutable(base / "receipts" / (sha256(receipt).hexdigest() + ".json"), receipt)
        payload = json.loads(raw)
        total = payload.get("totalAnnouncement")
        has_more = payload.get("hasMore")
        if type(total) is not int or total < 0 or type(has_more) is not bool:
            raise ValueError("CNINFO pagination metadata missing or invalid")
        if expected_total is not None and total != expected_total:
            raise ValueError("CNINFO catalog changed during pagination")
        expected_total = total
        rows = payload.get("announcements")
        if rows is None and total == 0:
            rows = []
        if not isinstance(rows, list) or (has_more and not rows):
            raise ValueError("CNINFO pagination returned invalid or stalled page")
        for row in rows:
            if not isinstance(row, dict) or row.get("secCode") != code:
                raise ValueError("CNINFO catalog security identity mismatch")
            announcement_id = str(row.get("announcementId", ""))
            if not announcement_id or announcement_id in seen:
                raise ValueError("CNINFO repeated or missing announcement identity")
            seen.add(announcement_id)
            announcements.append(row)
        pages.append(digest)
        if not has_more:
            if len(announcements) != total:
                raise ValueError("CNINFO catalog count mismatch")
            break
    else:
        raise ValueError("CNINFO pagination limit reached; catalog incomplete")
    combined = canonical(
        {
            "schema_version": 1,
            "symbol": symbol,
            "start": start,
            "end": end,
            "page_sha256s": pages,
            "stock_map_sha256": stock_sha,
            "announcements": announcements,
            "pagination_complete": True,
        }
    )
    combined_sha = sha256(combined).hexdigest()
    write_immutable(data_root / "cninfo_catalogs" / combined_sha / "response.json", combined)
    return {
        "symbol": symbol,
        "catalog_sha256": combined_sha,
        "announcements": announcements,
        "pagination_complete": True,
        "pages": len(pages),
    }


def archive_pdf(data_root: Path, adjunct_url: str, *, allow_network: bool) -> dict[str, str]:
    """Archive one official CNINFO PDF selected from an archived catalog row."""
    if (
        not allow_network
        or not adjunct_url.startswith("finalpage/")
        or ".." in Path(adjunct_url).parts
        or not adjunct_url.endswith(".PDF")
    ):
        raise ValueError("CNINFO PDF request is invalid")
    url = PDF_BASE + adjunct_url
    body = _get(url)
    if not body.startswith(b"%PDF"):
        raise ValueError("CNINFO response is not a PDF")
    digest = sha256(body).hexdigest()
    write_immutable(data_root / "cninfo_pdfs" / digest / "notice.pdf", body)
    return {"official_url": url, "raw_sha256": digest}


def _get(url: str) -> bytes:
    with urlopen(Request(url, headers=HEADERS), timeout=30) as response:
        return bytes(response.read())


def _post(url: str, form: bytes) -> bytes:
    with urlopen(Request(url, data=form, headers=HEADERS), timeout=30) as response:
        return bytes(response.read())
