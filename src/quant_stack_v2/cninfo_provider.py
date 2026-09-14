"""Bounded official CNINFO announcement discovery for EXQ-001."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from hashlib import sha256
from pathlib import Path
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from quant_stack.snapshot import write_immutable

STOCK_URL = "https://www.cninfo.com.cn/new/data/szse_stock.json"
QUERY_URL = "https://www.cninfo.com.cn/new/hisAnnouncement/query"
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
    form = urlencode(
        {
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
    ).encode()
    raw = _post(QUERY_URL, form)
    digest = sha256(raw).hexdigest()
    write_immutable(data_root / "cninfo_catalogs" / digest / "response.json", raw)
    receipt = {
        "symbol": symbol,
        "start": start,
        "end": end,
        "source_url": QUERY_URL,
        "raw_sha256": digest,
        "retrieved_at_utc": datetime.now(UTC).isoformat(),
    }
    write_immutable(
        data_root / "cninfo_catalogs" / digest / "receipt.json",
        json.dumps(receipt, sort_keys=True, separators=(",", ":")).encode() + b"\n",
    )
    payload = json.loads(raw)
    return {
        "symbol": symbol,
        "catalog_sha256": digest,
        "announcements": payload.get("announcements", []),
    }


def _get(url: str) -> bytes:
    with urlopen(Request(url, headers=HEADERS), timeout=30) as response:
        return bytes(response.read())


def _post(url: str, form: bytes) -> bytes:
    with urlopen(Request(url, data=form, headers=HEADERS), timeout=30) as response:
        return bytes(response.read())
