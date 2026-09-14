"""Free BaoStock daily status provider for V2 missing-session evidence."""

from __future__ import annotations

import csv
import importlib
import io
import json
import socket
import time
from collections.abc import Callable, Sequence
from dataclasses import asdict, dataclass
from datetime import UTC, date, datetime
from hashlib import sha256
from pathlib import Path

from quant_stack.snapshot import write_immutable

FIELDS = (
    "date",
    "code",
    "open",
    "high",
    "low",
    "close",
    "preclose",
    "volume",
    "amount",
    "tradestatus",
    "isST",
)
ADAPTER_VERSION = "1.0.0"


@dataclass(frozen=True)
class BaoStockRow:
    """One unadjusted BaoStock daily row used as independent evidence."""

    session: date
    code: str
    open: str
    high: str
    low: str
    close: str
    preclose: str
    volume: str
    amount: str
    tradestatus: int
    is_st: int


@dataclass(frozen=True)
class BaoStockManifest:
    """Content-addressed provenance for one complete symbol response."""

    symbol: str
    start_date: str
    end_date: str
    fields: tuple[str, ...]
    frequency: str
    adjustflag: str
    provider_version: str
    adapter_version: str
    raw_sha256: str
    row_count: int

    @property
    def identity_sha256(self) -> str:
        """Return deterministic request-and-content identity."""
        return sha256(_json(asdict(self))).hexdigest()


Query = Callable[[str, str, str, str, str, str], tuple[str, Sequence[Sequence[str]]]]


@dataclass(frozen=True)
class BaoStockCaptureFailure:
    """One bounded batch-capture failure retained instead of silently retrying forever."""

    symbol: str
    start_date: str
    end_date: str
    error: str


def capture_baostock_history(
    data_root: Path,
    *,
    symbol: str,
    start_date: date,
    end_date: date,
    allow_network: bool,
    query: Query | None = None,
    provider_version: str = "unknown",
) -> tuple[Path, BaoStockManifest, tuple[BaoStockRow, ...]]:
    """Capture raw unadjusted daily rows with explicit network authorization."""
    if not allow_network:
        raise ValueError("--allow-network is required for BaoStock capture")
    if start_date > end_date:
        raise ValueError("BaoStock date range is reversed")
    code = _provider_symbol(symbol)
    field_text = ",".join(FIELDS)
    error, raw_rows = (query or _live_query)(
        code, field_text, start_date.isoformat(), end_date.isoformat(), "d", "3"
    )
    if error != "0":
        raise ValueError(f"BaoStock query failed: {error}")
    raw = _csv_bytes(raw_rows)
    rows = _parse_rows(raw_rows, code)
    digest = sha256(raw).hexdigest()
    manifest = BaoStockManifest(
        symbol=symbol,
        start_date=start_date.isoformat(),
        end_date=end_date.isoformat(),
        fields=FIELDS,
        frequency="d",
        adjustflag="3",
        provider_version=provider_version,
        adapter_version=ADAPTER_VERSION,
        raw_sha256=digest,
        row_count=len(rows),
    )
    base = data_root / "baostock" / digest
    write_immutable(base / "response.csv", raw)
    receipt = {
        "schema_version": 1,
        "manifest_sha256": manifest.identity_sha256,
        "retrieved_at_utc": datetime.now(UTC).isoformat(),
        "provider": "baostock",
        "provider_version": provider_version,
        "request": {
            "method": "query_history_k_data_plus",
            "code": code,
            "fields": FIELDS,
            "start_date": start_date.isoformat(),
            "end_date": end_date.isoformat(),
            "frequency": "d",
            "adjustflag": "3",
        },
        "raw_sha256": digest,
    }
    receipt_bytes = _json(receipt) + b"\n"
    write_immutable(base / "receipts" / f"{sha256(receipt_bytes).hexdigest()}.json", receipt_bytes)
    manifest_path = data_root / "baostock_manifests" / manifest.identity_sha256 / "manifest.json"
    write_immutable(manifest_path, _json(asdict(manifest)) + b"\n")
    return manifest_path, manifest, rows


def capture_baostock_batch(
    data_root: Path,
    *,
    symbols: tuple[str, ...],
    start_date: date,
    end_date: date,
    allow_network: bool,
    query: Query | None = None,
    provider_version: str = "unknown",
) -> tuple[tuple[BaoStockManifest, ...], tuple[BaoStockCaptureFailure, ...]]:
    """Capture one fixed date span through one BaoStock login and retain failures."""
    if not allow_network:
        raise ValueError("--allow-network is required for BaoStock capture")
    if not symbols or tuple(sorted(set(symbols))) != symbols:
        raise ValueError("BaoStock batch requires sorted unique symbols")
    return capture_baostock_requests(
        data_root,
        requests=tuple((symbol, start_date, end_date) for symbol in symbols),
        allow_network=allow_network,
        query=query,
        provider_version=provider_version,
    )


def capture_baostock_requests(
    data_root: Path,
    *,
    requests: tuple[tuple[str, date, date], ...],
    allow_network: bool,
    query: Query | None = None,
    provider_version: str = "unknown",
) -> tuple[tuple[BaoStockManifest, ...], tuple[BaoStockCaptureFailure, ...]]:
    """Capture sorted symbol/date requests through one BaoStock login."""
    if not allow_network:
        raise ValueError("--allow-network is required for BaoStock capture")
    if not requests or tuple(sorted(requests)) != requests:
        raise ValueError("BaoStock requests must be sorted and unique")
    if any(start > end for _, start, end in requests):
        raise ValueError("BaoStock request has reversed dates")
    if query is not None:
        return _capture_requests(data_root, requests, query, provider_version)
    try:
        bs = importlib.import_module("baostock")
    except ImportError as error:
        raise ValueError("BaoStock package is not installed") from error
    previous_timeout = socket.getdefaulttimeout()
    socket.setdefaulttimeout(30.0)
    logged_in = False
    try:
        login = bs.login()
        if login.error_code != "0":
            return (), _request_failures(requests, "BaoStock login failed")
        logged_in = True

        def session_query(
            code: str, fields: str, start: str, end: str, frequency: str, adjustflag: str
        ) -> tuple[str, Sequence[Sequence[str]]]:
            result = bs.query_history_k_data_plus(
                code,
                fields,
                start_date=start,
                end_date=end,
                frequency=frequency,
                adjustflag=adjustflag,
            )
            rows: list[list[str]] = []
            while result.error_code == "0" and result.next():
                rows.append(result.get_row_data())
            return str(result.error_code), rows

        return _capture_requests(data_root, requests, session_query, provider_version)
    finally:
        if logged_in:
            bs.logout()
        socket.setdefaulttimeout(previous_timeout)


def _capture_requests(
    data_root: Path,
    requests: tuple[tuple[str, date, date], ...],
    query: Query,
    provider_version: str,
) -> tuple[tuple[BaoStockManifest, ...], tuple[BaoStockCaptureFailure, ...]]:
    """Write one immutable response per successful query while preserving all failures."""
    manifests: list[BaoStockManifest] = []
    failures: list[BaoStockCaptureFailure] = []
    for symbol, start_date, end_date in requests:
        try:
            _, manifest, _ = capture_baostock_history(
                data_root,
                symbol=symbol,
                start_date=start_date,
                end_date=end_date,
                allow_network=True,
                query=query,
                provider_version=provider_version,
            )
            manifests.append(manifest)
        except ValueError as error:
            failures.append(
                BaoStockCaptureFailure(
                    symbol=symbol,
                    start_date=start_date.isoformat(),
                    end_date=end_date.isoformat(),
                    error=str(error),
                )
            )
    return tuple(manifests), tuple(failures)


def _request_failures(
    requests: tuple[tuple[str, date, date], ...], error: str
) -> tuple[BaoStockCaptureFailure, ...]:
    """Record a login-level failure for each fixed request without retrying it independently."""
    return tuple(
        BaoStockCaptureFailure(symbol, start.isoformat(), end.isoformat(), error)
        for symbol, start, end in requests
    )


def _provider_symbol(symbol: str) -> str:
    if len(symbol) != 8 or symbol[:2] not in {"sh", "sz"} or not symbol[2:].isdigit():
        raise ValueError("BaoStock symbol must use sh/sz plus six digits")
    return f"{symbol[:2]}.{symbol[2:]}"


def _parse_rows(raw_rows: Sequence[Sequence[str]], expected_code: str) -> tuple[BaoStockRow, ...]:
    parsed: list[BaoStockRow] = []
    for raw in raw_rows:
        if (
            len(raw) != len(FIELDS)
            or raw[1] != expected_code
            or raw[9] not in {"0", "1"}
            or raw[10] not in {"0", "1"}
        ):
            raise ValueError("BaoStock returned an invalid daily row")
        parsed.append(
            BaoStockRow(
                session=date.fromisoformat(raw[0]),
                code=raw[1],
                open=raw[2],
                high=raw[3],
                low=raw[4],
                close=raw[5],
                preclose=raw[6],
                volume=raw[7],
                amount=raw[8],
                tradestatus=int(raw[9]),
                is_st=int(raw[10]),
            )
        )
    if len({item.session for item in parsed}) != len(parsed):
        raise ValueError("BaoStock returned duplicate sessions")
    return tuple(sorted(parsed, key=lambda item: item.session))


def _csv_bytes(rows: Sequence[Sequence[str]]) -> bytes:
    buffer = io.StringIO(newline="")
    writer = csv.writer(buffer, lineterminator="\n")
    writer.writerow(FIELDS)
    writer.writerows(rows)
    return buffer.getvalue().encode()


def _live_query(
    code: str, fields: str, start: str, end: str, frequency: str, adjustflag: str
) -> tuple[str, Sequence[Sequence[str]]]:
    try:
        bs = importlib.import_module("baostock")
    except ImportError as error:
        raise ValueError("BaoStock package is not installed") from error
    previous_timeout = socket.getdefaulttimeout()
    socket.setdefaulttimeout(30.0)
    last_error: OSError | None = None
    try:
        for attempt in range(3):
            logged_in = False
            try:
                login = bs.login()
                if login.error_code != "0":
                    last_error = OSError(f"BaoStock login failed: {login.error_code}")
                else:
                    logged_in = True
                    result = bs.query_history_k_data_plus(
                        code,
                        fields,
                        start_date=start,
                        end_date=end,
                        frequency=frequency,
                        adjustflag=adjustflag,
                    )
                    rows: list[list[str]] = []
                    while result.error_code == "0" and result.next():
                        rows.append(result.get_row_data())
                    return result.error_code, rows
            except (OSError, TimeoutError) as error:
                last_error = OSError(str(error))
            finally:
                if logged_in:
                    bs.logout()
            if attempt < 2:
                time.sleep(0.2 * (attempt + 1))
    finally:
        socket.setdefaulttimeout(previous_timeout)
    raise ValueError("BaoStock failed after three bounded attempts") from last_error


def _json(value: object) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
