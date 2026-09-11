"""SSE official suspension evidence capture for V2."""

from __future__ import annotations

import json
import time
from dataclasses import asdict, dataclass
from datetime import UTC, date, datetime
from hashlib import sha256
from pathlib import Path
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from quant_stack.snapshot import write_immutable

ENDPOINT = "https://query.sse.com.cn/commonSoaQuery.do"
SQL_ID = "GW_PL_JYTS_TFPXX"
ADAPTER_VERSION = "1.0.0"


@dataclass(frozen=True)
class SSEEvent:
    """One official SSE suspension result."""

    symbol: str
    start_date: date
    end_date: date
    reason: str
    end_reason: str


@dataclass(frozen=True)
class SSEManifest:
    """Immutable request and response provenance."""

    symbol: str
    start_date: str
    end_date: str
    raw_sha256: str
    event_count: int
    adapter_version: str

    @property
    def identity_sha256(self) -> str:
        return sha256(_json(asdict(self))).hexdigest()


def capture_sse_suspensions(
    data_root: Path, *, symbol: str, start: date, end: date, allow_network: bool
) -> tuple[Path, SSEManifest, tuple[SSEEvent, ...]]:
    """Fetch, validate and archive one SSE official interval query."""
    if not allow_network:
        raise ValueError("--allow-network is required for SSE suspension capture")
    if not symbol.startswith("sh") or start > end:
        raise ValueError("invalid SSE suspension request")
    params = {
        "sqlId": SQL_ID,
        "isPagination": "true",
        "pageHelp.pageSize": "100",
        "pageHelp.pageNo": "1",
        "productCode": symbol[2:],
        "keyWords": "",
        "startStopDate": start.strftime("%Y%m%d"),
        "endStopDate": end.strftime("%Y%m%d"),
    }
    raw, metadata = _fetch(f"{ENDPOINT}?{urlencode(params)}")
    events = _parse(raw, symbol)
    digest = sha256(raw).hexdigest()
    manifest = SSEManifest(
        symbol, start.isoformat(), end.isoformat(), digest, len(events), ADAPTER_VERSION
    )
    base = data_root / "sse_suspension" / digest
    write_immutable(base / "response.json", raw)
    receipt = {
        "schema_version": 1,
        "manifest_sha256": manifest.identity_sha256,
        "source_url": ENDPOINT,
        "request_parameters": params,
        "retrieved_at_utc": datetime.now(UTC).isoformat(),
        "http_metadata": metadata,
    }
    receipt_bytes = _json(receipt) + b"\n"
    write_immutable(base / "receipts" / f"{sha256(receipt_bytes).hexdigest()}.json", receipt_bytes)
    path = data_root / "sse_suspension_manifests" / manifest.identity_sha256 / "manifest.json"
    write_immutable(path, _json(asdict(manifest)) + b"\n")
    return path, manifest, events


def _parse(raw: bytes, symbol: str) -> tuple[SSEEvent, ...]:
    try:
        result = json.loads(raw)["result"]
        events = tuple(
            SSEEvent(
                symbol,
                datetime.strptime(item["startStopDate"], "%Y%m%d").date(),
                datetime.strptime(item["endStopDate"], "%Y%m%d").date(),
                str(item["stopReason"]),
                str(item["endStopReason"]),
            )
            for item in result
        )
    except (KeyError, TypeError, ValueError, json.JSONDecodeError) as error:
        raise ValueError("SSE suspension response has invalid schema") from error
    if any(item.symbol != symbol for item in events):
        raise ValueError("SSE suspension response symbol mismatch")
    return events


def _fetch(url: str) -> tuple[bytes, dict[str, str]]:
    last: OSError | None = None
    for attempt in range(3):
        try:
            request = Request(
                url,
                headers={
                    "Referer": "https://www.sse.com.cn/disclosure/dealinstruc/suspension/stock/",
                    "User-Agent": "quant-stack-v2/1.0",
                },
            )
            with urlopen(request, timeout=30) as response:
                return bytes(response.read()), {
                    **{k.lower(): v for k, v in response.headers.items()},
                    ":status": str(response.status),
                }
        except OSError as error:
            last = error
            if attempt < 2:
                time.sleep(0.2 * (attempt + 1))
    raise ValueError("SSE suspension capture failed after retries") from last


def _json(value: object) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
