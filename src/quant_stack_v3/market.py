"""Normalize the verified RQAlpha bundle into one causal research bar table."""

from __future__ import annotations

import json
import os
import tempfile
from bisect import bisect_left
from dataclasses import asdict, dataclass
from datetime import date
from hashlib import sha256
from pathlib import Path
from typing import TYPE_CHECKING

import numpy as np
import pandas as pd

from quant_stack.research_json import canonical_json
from quant_stack.snapshot import write_immutable
from quant_stack_v3.protocol import Protocol

if TYPE_CHECKING:
    import h5py  # type: ignore[import-untyped]


class MarketDataError(ValueError):
    """Raised when source rows cannot form a causal historical table."""


@dataclass(frozen=True)
class NormalizationReport:
    """Content identity and coverage of normalized historical bars."""

    schema_version: int
    bundle_tree_sha256: str
    bars_sha256: str
    rows: int
    symbols: int
    first_session: str
    last_session: str
    evaluation_sessions: int
    dropped_nonpositive_rows: int
    status: str


def normalize_bundle(
    bundle_root: Path,
    output_root: Path,
    protocol: Protocol,
    *,
    bundle_tree_sha256: str,
) -> tuple[Path, Path, NormalizationReport]:
    """Build an immutable raw-price and causal-adjustment table from verified HDF5 files."""
    import h5py

    calendar_values = np.load(bundle_root / "trading_dates.npy", allow_pickle=False)
    calendar = tuple(_date_int(item) for item in calendar_values)
    calendar_index = {item: index for index, item in enumerate(calendar)}
    try:
        evaluation_start = calendar.index(protocol.research.start)
        evaluation_end = calendar.index(protocol.research.end)
    except ValueError as error:
        raise MarketDataError("research boundaries are not bundle sessions") from error
    source_start = calendar[max(0, evaluation_start - protocol.research.maximum_lookback_sessions)]
    source_end = protocol.research.end
    suspended = _date_sets(bundle_root / "suspended_days.h5")
    st_days = _date_sets(bundle_root / "st_stock_days.h5")
    valid_starts, valid_ends = _lifecycle_overrides(bundle_root / "share_transformation.json")
    frames: list[pd.DataFrame] = []
    dropped = 0
    with (
        h5py.File(bundle_root / "stocks.h5", "r") as stocks,
        h5py.File(bundle_root / "ex_cum_factor.h5", "r") as factors,
    ):
        for provider_symbol in sorted(stocks.keys()):
            symbol = _symbol(provider_symbol)
            if symbol is None:
                continue
            values = stocks[provider_symbol][:]
            if not len(values):
                continue
            dates = np.asarray([_date_int(item) for item in values["datetime"]], dtype=object)
            selected = np.asarray(
                [
                    source_start <= item <= source_end
                    and item >= valid_starts.get(provider_symbol, date.min)
                    and item < valid_ends.get(provider_symbol, date.max)
                    for item in dates
                ],
                dtype=bool,
            )
            if not selected.any():
                continue
            values = values[selected]
            dates = dates[selected]
            valid = (
                (values["open"] > 0)
                & (values["high"] > 0)
                & (values["low"] > 0)
                & (values["close"] > 0)
                & (values["volume"] >= 0)
                & (values["total_turnover"] >= 0)
            )
            dropped += int((~valid).sum())
            values = values[valid]
            dates = dates[valid]
            if not len(values):
                continue
            adjustment = _factors_for_dates(factors.get(provider_symbol), dates)
            ordinals = np.asarray([calendar_index[item] for item in dates], dtype=np.int32)
            first_date = _date_int(stocks[provider_symbol][0]["datetime"])
            first_ordinal = calendar_index.get(first_date, bisect_left(calendar, first_date))
            frame = pd.DataFrame(
                {
                    "session": pd.to_datetime(dates),
                    "symbol": symbol,
                    "raw_open": values["open"].astype(float),
                    "raw_high": values["high"].astype(float),
                    "raw_low": values["low"].astype(float),
                    "raw_close": values["close"].astype(float),
                    "previous_close": values["prev_close"].astype(float),
                    "limit_up": values["limit_up"].astype(float),
                    "limit_down": values["limit_down"].astype(float),
                    "raw_volume": values["volume"].astype(float),
                    "amount": values["total_turnover"].astype(float),
                    "calc_open": values["open"].astype(float) * adjustment,
                    "calc_high": values["high"].astype(float) * adjustment,
                    "calc_low": values["low"].astype(float) * adjustment,
                    "calc_close": values["close"].astype(float) * adjustment,
                    "calc_volume": values["volume"].astype(float) / adjustment,
                    "st": [item in st_days.get(provider_symbol, set()) for item in dates],
                    "suspended": [item in suspended.get(provider_symbol, set()) for item in dates],
                    "session_ordinal": ordinals,
                    "listed_sessions": ordinals - first_ordinal + 1,
                    "exchange": "SSE" if symbol.startswith("sh") else "SZSE",
                    "board": [_board(symbol)] * len(values),
                }
            )
            frames.append(frame)
    if not frames:
        raise MarketDataError("bundle yielded no normalized stock bars")
    bars = pd.concat(frames, ignore_index=True).sort_values(["session", "symbol"], kind="stable")
    duplicate = bars.duplicated(["session", "symbol"])
    if duplicate.any():
        raise MarketDataError("bundle contains duplicate symbol-session bars")
    output_root.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=".bars-", suffix=".parquet", dir=output_root
    )
    os.close(descriptor)
    temporary = Path(temporary_name)
    try:
        bars.to_parquet(temporary, index=False, compression="zstd")
        digest = _file_sha256(temporary)
        destination = output_root / "normalized" / digest / "bars.parquet"
        destination.parent.mkdir(parents=True, exist_ok=True)
        if destination.exists():
            if _file_sha256(destination) != digest:
                raise MarketDataError("existing normalized bars conflict with their identity")
        else:
            temporary.replace(destination)
        report = NormalizationReport(
            schema_version=1,
            bundle_tree_sha256=bundle_tree_sha256,
            bars_sha256=digest,
            rows=len(bars),
            symbols=int(bars.symbol.nunique()),
            first_session=str(bars.session.min().date()),
            last_session=str(bars.session.max().date()),
            evaluation_sessions=evaluation_end - evaluation_start + 1,
            dropped_nonpositive_rows=dropped,
            status="NORMALIZED_HISTORICAL_RESEARCH_ONLY",
        )
        encoded = canonical_json(asdict(report)) + b"\n"
        report_path = output_root / "normalization" / digest / "report.json"
        write_immutable(report_path, encoded)
        return destination, report_path, report
    finally:
        temporary.unlink(missing_ok=True)


def _date_sets(path: Path) -> dict[str, set[date]]:
    import h5py

    output: dict[str, set[date]] = {}
    with h5py.File(path, "r") as handle:
        for symbol in handle.keys():
            output[symbol] = {
                parsed
                for item in handle[symbol][:]
                if (parsed := _optional_date_int(item)) is not None
            }
    return output


def _factors_for_dates(dataset: h5py.Dataset | None, dates: np.ndarray) -> np.ndarray:
    if dataset is None or not len(dataset):
        return np.ones(len(dates), dtype=float)
    values = dataset[:]
    starts = np.asarray(
        [date.min if int(item) == 0 else _date_int(item) for item in values["start_date"]],
        dtype=object,
    )
    factors = values["ex_cum_factor"].astype(float)
    positions = np.searchsorted(starts, dates, side="right") - 1
    positions = np.maximum(positions, 0)
    selected = np.asarray(factors[positions], dtype=float)
    if not np.isfinite(selected).all() or (selected <= 0).any():
        raise MarketDataError("bundle contains nonpositive adjustment factors")
    return selected


def _date_int(value: object) -> date:
    integer = int(float(str(value)))
    if integer > 99_999_999:
        integer //= 1_000_000
    text = f"{integer:08d}"
    return date(int(text[:4]), int(text[4:6]), int(text[6:]))


def _optional_date_int(value: object) -> date | None:
    try:
        number = float(str(value))
        if not np.isfinite(number) or int(number) <= 0:
            return None
        return _date_int(value)
    except (OverflowError, ValueError):
        return None


def _symbol(value: str) -> str | None:
    if len(value) != 11 or value[6:] not in {".XSHG", ".XSHE"} or not value[:6].isdigit():
        return None
    code = value[:6]
    if value.endswith(".XSHG") and code.startswith(("600", "601", "603", "605", "688", "689")):
        return "sh" + code
    if value.endswith(".XSHE") and code.startswith(
        ("000", "001", "002", "003", "300", "301", "302")
    ):
        return "sz" + code
    return None


def _lifecycle_overrides(path: Path) -> tuple[dict[str, date], dict[str, date]]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise MarketDataError("share transformation payload must be a mapping")
    starts: dict[str, date] = {}
    ends: dict[str, date] = {}
    for predecessor, item in payload.items():
        if not isinstance(item, dict):
            raise MarketDataError("share transformation record must be a mapping")
        effective = date.fromisoformat(str(item["effective_date"]))
        ends[str(predecessor)] = effective
        if str(item.get("event")) in {"code_change", "listing board switch"}:
            starts[str(item["successor"])] = effective
    return starts, ends


def _board(symbol: str) -> str:
    code = symbol[2:]
    if symbol.startswith("sh") and code.startswith("688"):
        return "star"
    if symbol.startswith("sz") and code.startswith(("300", "301")):
        return "chinext"
    return "main"


def _file_sha256(path: Path) -> str:
    digest = sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()
