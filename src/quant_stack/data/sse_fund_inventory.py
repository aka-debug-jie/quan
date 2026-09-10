"""Immutable capture of the SSE official fund-announcement inventory."""

from __future__ import annotations

import json
import time
from dataclasses import dataclass
from datetime import UTC, date, datetime
from hashlib import sha256
from pathlib import Path
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from quant_stack.snapshot import write_immutable

SSE_FUND_INVENTORY_ENDPOINT = "https://query.sse.com.cn/commonQuery.do"
SSE_FUND_INVENTORY_REFERER = "https://www.sse.com.cn/disclosure/fund/announcement/"
SSE_FUND_INVENTORY_PARSER_VERSION = "1.0.0"


class SSEFundInventoryError(ValueError):
    """Raised when the official announcement directory cannot be safely archived."""


@dataclass(frozen=True)
class SSEFundInventoryPayload:
    """One unmodified SSE response and its transport provenance."""

    symbol: str
    start_date: date
    end_date: date
    source_url: str
    request_parameters: dict[str, str]
    http_metadata: dict[str, str]
    retrieved_at: datetime
    raw_bytes: bytes


@dataclass(frozen=True)
class SSEFundAnnouncement:
    """One official directory row relevant to corporate-action discovery."""

    disclosed_on: date
    title: str
    url: str


def fetch_sse_fund_inventory(
    symbol: str, start_date: date, end_date: date
) -> SSEFundInventoryPayload:
    """Fetch one complete SSE fund-announcement directory response with bounded retries."""
    parameters = _request_parameters(symbol, start_date, end_date)
    request = Request(
        f"{SSE_FUND_INVENTORY_ENDPOINT}?{urlencode(parameters)}",
        headers={
            "Referer": SSE_FUND_INVENTORY_REFERER,
            "User-Agent": "quant-stack-sse-inventory/1.0",
        },
    )
    last_error: Exception | None = None
    for attempt in range(3):
        try:
            with urlopen(request, timeout=30) as response:
                body = bytes(response.read())
                metadata = {key.lower(): value for key, value in response.headers.items()}
                metadata[":status"] = str(response.status)
            _validated_rows(body, symbol)
            return SSEFundInventoryPayload(
                symbol=symbol,
                start_date=start_date,
                end_date=end_date,
                source_url=SSE_FUND_INVENTORY_ENDPOINT,
                request_parameters=parameters,
                http_metadata=metadata,
                retrieved_at=datetime.now(UTC),
                raw_bytes=body,
            )
        except (OSError, SSEFundInventoryError) as error:
            last_error = error
            if attempt < 2:
                time.sleep(0.2 * (attempt + 1))
    raise SSEFundInventoryError("unable to capture complete SSE fund inventory") from last_error


def persist_sse_fund_inventory(payload: SSEFundInventoryPayload, data_root: Path) -> Path:
    """Persist the exact official response and a separate retrieval receipt."""
    rows = _validated_rows(payload.raw_bytes, payload.symbol)
    digest = sha256(payload.raw_bytes).hexdigest()
    path = data_root / "raw" / "sse_fund_inventory" / digest / "response.json"
    write_immutable(path, payload.raw_bytes)
    receipt = {
        "symbol": payload.symbol,
        "start_date": payload.start_date.isoformat(),
        "end_date": payload.end_date.isoformat(),
        "source_url": payload.source_url,
        "request_parameters": payload.request_parameters,
        "http_metadata": payload.http_metadata,
        "retrieved_at": payload.retrieved_at.isoformat(),
        "parser_version": SSE_FUND_INVENTORY_PARSER_VERSION,
        "sha256": digest,
        "row_count": len(rows),
    }
    receipt_path = path.with_name("receipt.json")
    if not receipt_path.exists():
        write_immutable(
            receipt_path,
            json.dumps(receipt, ensure_ascii=False, sort_keys=True, indent=2).encode("utf-8")
            + b"\n",
        )
    return path


def load_relevant_sse_fund_announcements(
    digest: str,
    receipt_sha256: str,
    symbol: str,
    required_start: date,
    required_end: date,
    data_root: Path,
) -> tuple[SSEFundAnnouncement, ...]:
    """Load corporate-action directory rows from one hash-verified official response."""
    path = data_root / "raw" / "sse_fund_inventory" / digest / "response.json"
    if not path.is_file() or sha256(path.read_bytes()).hexdigest() != digest:
        raise SSEFundInventoryError("SSE fund inventory is missing or hash-invalid")
    receipt_path = path.with_name("receipt.json")
    if (
        not receipt_path.is_file()
        or sha256(receipt_path.read_bytes()).hexdigest() != receipt_sha256
    ):
        raise SSEFundInventoryError("SSE fund inventory receipt is missing or hash-invalid")
    try:
        receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
        captured_start = date.fromisoformat(receipt["start_date"])
        captured_end = date.fromisoformat(receipt["end_date"])
    except (KeyError, TypeError, ValueError, json.JSONDecodeError) as error:
        raise SSEFundInventoryError("SSE fund inventory receipt has an unexpected shape") from error
    if (
        receipt.get("symbol") != symbol
        or receipt.get("sha256") != digest
        or receipt.get("parser_version") != SSE_FUND_INVENTORY_PARSER_VERSION
        or captured_start > required_start
        or captured_end < required_end
    ):
        raise SSEFundInventoryError("SSE fund inventory receipt does not cover the research range")
    relevant: list[SSEFundAnnouncement] = []
    for row in _validated_rows(path.read_bytes(), symbol):
        title = str(row["TITLE"])
        if not any(
            keyword in title for keyword in ("收益分配", "分红公告", "份额折算", "份额拆分")
        ):
            continue
        url = str(row["URL"])
        if url.startswith("/"):
            url = f"https://www.sse.com.cn{url}"
        relevant.append(
            SSEFundAnnouncement(
                disclosed_on=date.fromisoformat(str(row["SSEDATE"])),
                title=title,
                url=url,
            )
        )
    return tuple(relevant)


def _request_parameters(symbol: str, start_date: date, end_date: date) -> dict[str, str]:
    return {
        "isPagination": "true",
        "pageHelp.pageSize": "2000",
        "pageHelp.pageNo": "1",
        "pageHelp.beginPage": "1",
        "pageHelp.cacheSize": "1",
        "pageHelp.endPage": "1",
        "type": "inParams",
        "sqlId": "COMMON_PL_JJXX_JJGG_NEW_L",
        "TITLE": "",
        "SECURITY_CODE": symbol,
        "BULLETIN_TYPE": (
            "reits01,fund01,reits02,fund02,reits03,fund03,reits04,fund04,"
            "reits05,fund05,reits06,fund06"
        ),
        "START_DATE": start_date.isoformat(),
        "END_DATE": end_date.isoformat(),
        "DATE_DESC": "1",
    }


def _validated_rows(raw_bytes: bytes, symbol: str) -> list[dict[str, object]]:
    try:
        payload = json.loads(raw_bytes)
        page_help = payload["pageHelp"]
        rows = payload["result"]
        total = page_help["total"]
    except (KeyError, TypeError, json.JSONDecodeError) as error:
        raise SSEFundInventoryError("SSE fund inventory has an unexpected shape") from error
    if not isinstance(rows, list) or not isinstance(total, int) or len(rows) != total:
        raise SSEFundInventoryError("SSE fund inventory response is not a complete page")
    if any(not isinstance(row, dict) or row.get("SECURITY_CODE") != symbol for row in rows):
        raise SSEFundInventoryError("SSE fund inventory contains an unexpected security")
    return rows
