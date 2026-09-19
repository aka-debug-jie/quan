"""Archived Tencent daily-history evidence through the installed AKShare adapter."""

from __future__ import annotations

import csv
import importlib
import io
import json
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict, dataclass
from datetime import UTC, date, datetime
from hashlib import sha256
from pathlib import Path
from typing import cast

import pandas as pd

from quant_stack.snapshot import write_immutable

FIELDS = ("date", "open", "close", "high", "low", "volume", "amount")
Query = Callable[[str, str, str], pd.DataFrame]


@dataclass(frozen=True)
class TencentManifest:
    """One raw Tencent response, which is independent provider evidence only."""

    symbol: str
    start_date: str
    end_date: str
    fields: tuple[str, ...]
    provider_version: str
    raw_sha256: str
    row_count: int

    @property
    def identity_sha256(self) -> str:
        return sha256(_json(asdict(self))).hexdigest()


@dataclass(frozen=True)
class TencentFailure:
    """A retained bounded provider failure."""

    symbol: str
    span: str
    error: str


def capture_history(
    data_root: Path,
    *,
    symbol: str,
    start: date,
    end: date,
    allow_network: bool,
    query: Query | None = None,
    provider_version: str = "unknown",
) -> TencentManifest:
    """Archive one approved unadjusted Tencent history span."""
    if not allow_network:
        raise ValueError("--allow-network is required for Tencent capture")
    if start > end:
        raise ValueError("Tencent history request has reversed dates")
    frame = (query or _live_query)(symbol, start.strftime("%Y%m%d"), end.strftime("%Y%m%d"))
    rows = _rows(frame, start, end)
    raw = _csv(rows)
    digest = sha256(raw).hexdigest()
    manifest = TencentManifest(
        symbol, start.isoformat(), end.isoformat(), FIELDS, provider_version, digest, len(rows)
    )
    base = data_root / "tencent_finance" / digest
    write_immutable(base / "response.csv", raw)
    receipt = {
        "schema_version": 1,
        "provider": "tencent_finance_via_akshare",
        "provider_version": provider_version,
        "retrieved_at_utc": datetime.now(UTC).isoformat(),
        "request": {
            "method": "stock_zh_a_hist_tx",
            "symbol": symbol,
            "start_date": start.strftime("%Y%m%d"),
            "end_date": end.strftime("%Y%m%d"),
            "adjust": "",
        },
        "raw_sha256": digest,
        "manifest_sha256": manifest.identity_sha256,
    }
    receipt_bytes = _json(receipt) + b"\n"
    write_immutable(base / "receipts" / f"{sha256(receipt_bytes).hexdigest()}.json", receipt_bytes)
    write_immutable(
        data_root / "tencent_finance_manifests" / manifest.identity_sha256 / "manifest.json",
        _json(asdict(manifest)) + b"\n",
    )
    return manifest


def capture_history_batch(
    data_root: Path,
    *,
    requests: tuple[tuple[str, date, date], ...],
    allow_network: bool,
    query: Query | None = None,
    provider_version: str = "unknown",
    workers: int = 2,
) -> tuple[tuple[TencentManifest, ...], tuple[TencentFailure, ...]]:
    """Capture approved history spans with conservative bounded concurrency."""
    if not allow_network:
        raise ValueError("--allow-network is required for Tencent capture")
    if not requests or tuple(sorted(set(requests))) != requests or not 1 <= workers <= 2:
        raise ValueError("Tencent requests must be unique/sorted and workers 1..2")

    def one(request: tuple[str, date, date]) -> TencentManifest | TencentFailure:
        symbol, start, end = request
        try:
            return capture_history(
                data_root,
                symbol=symbol,
                start=start,
                end=end,
                allow_network=True,
                query=query,
                provider_version=provider_version,
            )
        except (ValueError, OSError) as error:
            return TencentFailure(symbol, f"{start.isoformat()}:{end.isoformat()}", str(error))

    with ThreadPoolExecutor(max_workers=workers) as executor:
        outcomes = tuple(executor.map(one, requests))
    manifests = tuple(
        sorted(
            (item for item in outcomes if isinstance(item, TencentManifest)),
            key=lambda item: (item.symbol, item.start_date, item.end_date),
        )
    )
    failures = tuple(
        sorted(
            (item for item in outcomes if isinstance(item, TencentFailure)),
            key=lambda item: (item.symbol, item.span),
        )
    )
    return manifests, failures


def _live_query(symbol: str, start: str, end: str) -> pd.DataFrame:
    ak = importlib.import_module("akshare")
    return cast(
        pd.DataFrame,
        ak.stock_zh_a_hist_tx(symbol=symbol, start_date=start, end_date=end, adjust="", timeout=30),
    )


def _rows(frame: pd.DataFrame, start: date, end: date) -> list[dict[str, str]]:
    if frame.empty:
        return []
    required = set(FIELDS)
    if not required <= set(frame.columns):
        raise ValueError("Tencent response lacks daily raw fields")
    rows = [{field: str(row[field]) for field in FIELDS} for _, row in frame.iterrows()]
    sessions = [date.fromisoformat(row["date"]) for row in rows]
    if len(set(sessions)) != len(sessions) or any(day < start or day > end for day in sessions):
        raise ValueError("Tencent response is outside requested history span")
    return rows


def _csv(rows: list[dict[str, str]]) -> bytes:
    buffer = io.StringIO(newline="")
    writer = csv.writer(buffer, lineterminator="\n")
    writer.writerow(FIELDS)
    for row in rows:
        writer.writerow([row[field] for field in FIELDS])
    return buffer.getvalue().encode()


def _json(value: object) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
