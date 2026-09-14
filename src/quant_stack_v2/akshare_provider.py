"""Bounded, archived AKShare/Eastmoney daily raw evidence for EXQ-001."""

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
ADAPTER_VERSION = "1.0.0"
Query = Callable[[str, str, str], pd.DataFrame]


@dataclass(frozen=True)
class AKShareManifest:
    """One immutable provider response, never official exchange confirmation."""

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
class AKShareFailure:
    """One bounded provider failure retained in the capture receipt."""

    symbol: str
    session: str
    error: str


def capture_daily(
    data_root: Path,
    *,
    symbol: str,
    session: date,
    allow_network: bool,
    query: Query | None = None,
    provider_version: str = "unknown",
) -> AKShareManifest:
    """Archive one unadjusted daily response for one exact candidate key."""
    if not allow_network:
        raise ValueError("--allow-network is required for AKShare capture")
    frame = (query or _live_query)(
        _provider_symbol(symbol), session.strftime("%Y%m%d"), session.strftime("%Y%m%d")
    )
    raw = _csv(frame)
    rows = _validate(frame, session)
    digest = sha256(raw).hexdigest()
    manifest = AKShareManifest(
        symbol,
        session.isoformat(),
        session.isoformat(),
        FIELDS,
        provider_version,
        digest,
        len(rows),
    )
    base = data_root / "akshare_eastmoney" / digest
    write_immutable(base / "response.csv", raw)
    receipt = {
        "schema_version": 1,
        "provider": "akshare_eastmoney",
        "provider_version": provider_version,
        "adapter_version": ADAPTER_VERSION,
        "retrieved_at_utc": datetime.now(UTC).isoformat(),
        "request": {
            "method": "stock_zh_a_hist",
            "symbol": _provider_symbol(symbol),
            "period": "daily",
            "start_date": session.strftime("%Y%m%d"),
            "end_date": session.strftime("%Y%m%d"),
            "adjust": "",
        },
        "raw_sha256": digest,
        "manifest_sha256": manifest.identity_sha256,
    }
    receipt_bytes = _json(receipt) + b"\n"
    write_immutable(base / "receipts" / f"{sha256(receipt_bytes).hexdigest()}.json", receipt_bytes)
    write_immutable(
        data_root / "akshare_eastmoney_manifests" / manifest.identity_sha256 / "manifest.json",
        _json(asdict(manifest)) + b"\n",
    )
    return manifest


def capture_batch(
    data_root: Path,
    *,
    requests: tuple[tuple[str, date], ...],
    allow_network: bool,
    query: Query | None = None,
    provider_version: str = "unknown",
    workers: int = 4,
) -> tuple[tuple[AKShareManifest, ...], tuple[AKShareFailure, ...]]:
    """Capture disjoint exact dates with bounded provider concurrency."""
    if not allow_network:
        raise ValueError("--allow-network is required for AKShare capture")
    if not requests or tuple(sorted(set(requests))) != requests or not 1 <= workers <= 4:
        raise ValueError("AKShare requests must be unique/sorted and workers 1..4")

    def one(request: tuple[str, date]) -> AKShareManifest | AKShareFailure:
        symbol, session = request
        try:
            return capture_daily(
                data_root,
                symbol=symbol,
                session=session,
                allow_network=True,
                query=query,
                provider_version=provider_version,
            )
        except (ValueError, OSError) as error:
            return AKShareFailure(symbol, session.isoformat(), str(error))

    with ThreadPoolExecutor(max_workers=workers) as executor:
        outcomes = tuple(executor.map(one, requests))
    manifests = tuple(
        sorted(
            (item for item in outcomes if isinstance(item, AKShareManifest)),
            key=lambda item: item.symbol,
        )
    )
    failures = tuple(
        sorted(
            (item for item in outcomes if isinstance(item, AKShareFailure)),
            key=lambda item: item.symbol,
        )
    )
    return manifests, failures


def _provider_symbol(symbol: str) -> str:
    if len(symbol) != 8 or symbol[:2] not in {"sh", "sz"} or not symbol[2:].isdigit():
        raise ValueError("AKShare symbol must use sh/sz plus six digits")
    return symbol[2:]


def _live_query(symbol: str, start: str, end: str) -> pd.DataFrame:
    ak = importlib.import_module("akshare")
    return cast(
        pd.DataFrame,
        ak.stock_zh_a_hist(
            symbol=symbol, period="daily", start_date=start, end_date=end, adjust=""
        ),
    )


def _validate(frame: pd.DataFrame, session: date) -> list[dict[str, str]]:
    required = {"日期", "开盘", "收盘", "最高", "最低", "成交量", "成交额"}
    if not required <= set(frame.columns):
        raise ValueError("AKShare response lacks daily raw fields")
    rows = [
        {
            "date": str(row["日期"]),
            "open": str(row["开盘"]),
            "close": str(row["收盘"]),
            "high": str(row["最高"]),
            "low": str(row["最低"]),
            "volume": str(row["成交量"]),
            "amount": str(row["成交额"]),
        }
        for _, row in frame.iterrows()
    ]
    if any(row["date"] != session.isoformat() for row in rows) or len(rows) > 1:
        raise ValueError("AKShare response is outside exact requested session")
    return rows


def _csv(frame: pd.DataFrame) -> bytes:
    buffer = io.StringIO(newline="")
    writer = csv.writer(buffer, lineterminator="\n")
    writer.writerow(FIELDS)
    for row in (
        _validate(frame, date.fromisoformat(str(frame.iloc[0]["日期"]))) if not frame.empty else []
    ):
        writer.writerow([row[field] for field in FIELDS])
    return buffer.getvalue().encode()


def _json(value: object) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
