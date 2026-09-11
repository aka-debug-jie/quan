"""Offline-first Yahoo ETF adjusted-only snapshot provider."""

from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from decimal import Decimal, InvalidOperation
from hashlib import sha256
from pathlib import Path
from time import sleep
from typing import Any
from urllib.parse import quote, urlencode
from urllib.request import Request, urlopen

from quant_stack.models import ManifestFile
from quant_stack.snapshot import write_immutable

ADAPTER_VERSION = "1.0.0"
RESEARCH_ADJUSTED_ONLY = "RESEARCH_ADJUSTED_ONLY"
YAHOO_DATASET_ID = "yahoo_global_etf_research_v1"
REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
SEALED_EXTERNAL_ROOT = Path("/srv/quant-v2/sealed_holdout/data/external")
DEFAULT_YAHOO_ETF_SYMBOLS = (
    "MCHI",
    "SPY",
    "EFA",
    "IEF",
    "GLD",
    "DBC",
    "BIL",
)
YAHOO_HISTORY_URL_TEMPLATE = "https://query1.finance.yahoo.com/v8/finance/chart/{symbol}?{query}"
YAHOO_HEADERS = {
    "User-Agent": "quant-stack-yahoo-provider/1.0",
    "Accept": "application/json",
}
DEFAULT_MAX_ATTEMPTS = 3
DEFAULT_RETRY_SECONDS = 1.0
MINIMUM_HISTORY_SESSIONS = 1260


class YahooProviderError(ValueError):
    """Base class for one Yahoo snapshot or parse failure."""


class YahooNetworkDisabled(YahooProviderError):
    """Raised when Yahoo network fetch is attempted without explicit permission."""


@dataclass(frozen=True)
class YahooFetchPayload:
    """Immutable response bytes plus transport metadata for one symbol."""

    symbol: str
    source_url: str
    canonical_request: str
    request_parameters: dict[str, str]
    retrieved_at: datetime
    raw_bytes: bytes
    http_metadata: dict[str, str]
    raw_sha256: str
    adapter_version: str = ADAPTER_VERSION


@dataclass(frozen=True)
class YahooAdjustedClose:
    """One parsed adjusted daily close."""

    symbol: str
    trading_date: date
    adjusted_close: Decimal


@dataclass(frozen=True)
class YahooCorporateAction:
    """One dividend or split extracted from Yahoo chart events."""

    symbol: str
    trading_date: date
    event_type: str
    value: Decimal


@dataclass(frozen=True)
class YahooDataAnomaly:
    """One data-quality issue captured while parsing one symbol."""

    symbol: str
    kind: str
    detail: str


@dataclass(frozen=True)
class YahooProviderManifest:
    """Manifest-like receipt for one symbol response and parsed artifact."""

    symbol: str
    manifest_id: str
    source_url: str
    canonical_request: str
    request_parameters: dict[str, str]
    adapter_version: str
    retrieved_at: datetime
    http_metadata: dict[str, str]
    raw_file: ManifestFile
    normalized_file: ManifestFile
    row_count: int
    event_count: int
    first_trading_date: date
    last_trading_date: date
    raw_sha256: str


@dataclass(frozen=True)
class YahooSymbolSnapshot:
    """One symbol-level Yahoo adjusted-only snapshot."""

    manifest: YahooProviderManifest
    adjusted_bars: tuple[YahooAdjustedClose, ...]
    events: tuple[YahooCorporateAction, ...]
    anomalies: tuple[YahooDataAnomaly, ...]


@dataclass(frozen=True)
class YahooSnapshotReport:
    """Shared-date/quality aggregate for a fixed-vintage Yahoo ETF universe."""

    symbol_snapshots: tuple[YahooSymbolSnapshot, ...]
    common_trading_dates: tuple[date, ...]
    anomalies: tuple[YahooDataAnomaly, ...]

    @property
    def identity_sha256(self) -> str:
        """Return a stable report ID based only on immutable symbol snapshot identities."""
        return _sha256(
            _canonical_json_bytes(
                {
                    "manifests": [item.manifest.manifest_id for item in self.symbol_snapshots],
                    "common_trading_dates": [
                        item.isoformat() for item in self.common_trading_dates
                    ],
                    "anomalies": [item.__dict__ for item in self.anomalies],
                    "usage_level": RESEARCH_ADJUSTED_ONLY,
                }
            )
        )


def default_fetcher(url: str) -> tuple[bytes, dict[str, str], str]:
    """Fetch JSON through stdlib urllib and return bytes plus headers metadata."""
    request = Request(url, headers=YAHOO_HEADERS)
    with urlopen(request, timeout=30) as response:
        raw_bytes = response.read()
        metadata = {key.lower(): value for key, value in response.headers.items()}
        metadata[":status"] = str(response.status)
    return raw_bytes, metadata, str(response.status)


Fetcher = Callable[[str], tuple[bytes, dict[str, str], str]]


class YahooETFAdapter:
    """Fetch-and-parse adapter used only for adjusted research-only snapshots."""

    def __init__(
        self,
        *,
        allow_network: bool = False,
        fetcher: Fetcher | None = None,
        max_attempts: int = DEFAULT_MAX_ATTEMPTS,
        retry_delay_seconds: float = DEFAULT_RETRY_SECONDS,
        sleep_fn: Callable[[float], None] = sleep,
        as_of: date | None = None,
    ) -> None:
        if max_attempts < 1:
            raise ValueError("max_attempts must be at least one")
        if retry_delay_seconds < 0:
            raise ValueError("retry_delay_seconds must not be negative")
        self._allow_network = allow_network
        self._fetcher = fetcher or default_fetcher
        self._max_attempts = max_attempts
        self._retry_delay_seconds = retry_delay_seconds
        self._sleep_fn = sleep_fn
        self._as_of = as_of or datetime.now(UTC).date()

    def fetch(self, symbol: str) -> YahooFetchPayload:
        """Fetch one adjusted-only Yahoo response and record transport metadata."""
        if not self._allow_network:
            raise YahooNetworkDisabled("network access is disallowed for this adapter run")
        source_url, canonical_request, params = _build_request(symbol, self._as_of)
        last_error: Exception | None = None
        for attempt in range(1, self._max_attempts + 1):
            try:
                raw_bytes, metadata, status = self._fetcher(source_url)
                metadata = {key.lower(): value for key, value in metadata.items()}
                metadata[":status"] = status
                return YahooFetchPayload(
                    symbol=symbol,
                    source_url=source_url,
                    canonical_request=canonical_request,
                    request_parameters=params,
                    retrieved_at=datetime.now(UTC),
                    raw_bytes=raw_bytes,
                    raw_sha256=_sha256(raw_bytes),
                    http_metadata=metadata,
                )
            except OSError as error:
                last_error = error
            except YahooProviderError as error:
                last_error = error
            if attempt < self._max_attempts:
                self._sleep_fn(self._retry_delay_seconds)
        raise YahooProviderError(
            f"Yahoo fetch for {symbol} failed after {self._max_attempts} attempts"
        ) from last_error


def snapshot_yahoo_symbol(
    symbol: str,
    data_root: Path,
    *,
    adapter: YahooETFAdapter,
) -> YahooSymbolSnapshot:
    """Persist one symbol's adjusted close / events and return an immutable snapshot."""
    payload = adapter.fetch(symbol)
    adjusted, events, anomalies = parse_yahoo_payload(payload)
    return persist_yahoo_symbol_snapshot(payload, adjusted, events, anomalies, data_root)


def snapshot_yahoo_universe(
    data_root: Path,
    *,
    symbols: tuple[str, ...] = DEFAULT_YAHOO_ETF_SYMBOLS,
    adapter: YahooETFAdapter | None = None,
    allow_network: bool = False,
    as_of: date | None = None,
) -> YahooSnapshotReport:
    """Persist a fixed-universe adjusted-only Yahoo ETF snapshot with shared-date report."""
    effective_adapter = adapter or YahooETFAdapter(allow_network=allow_network, as_of=as_of)
    symbol_snapshots: list[YahooSymbolSnapshot] = []
    anomalies: list[YahooDataAnomaly] = []
    for symbol in symbols:
        try:
            symbol_snapshots.append(
                snapshot_yahoo_symbol(
                    symbol=symbol,
                    data_root=data_root,
                    adapter=effective_adapter,
                )
            )
        except YahooProviderError as error:
            anomalies.append(
                YahooDataAnomaly(
                    symbol=symbol,
                    kind="snapshot_failed",
                    detail=str(error),
                )
            )
    date_sets = [set(trading_dates(snapshot)) for snapshot in symbol_snapshots]
    if not date_sets:
        common: tuple[date, ...] = ()
    else:
        common_dates = set.intersection(*date_sets)
        common = tuple(sorted(common_dates))
    for symbol_snapshot in symbol_snapshots:
        anomalies.extend(symbol_snapshot.anomalies)
        if len(symbol_snapshot.adjusted_bars) < MINIMUM_HISTORY_SESSIONS:
            anomalies.append(
                YahooDataAnomaly(
                    symbol_snapshot.manifest.symbol,
                    "insufficient_history",
                    (
                        f"{symbol_snapshot.manifest.symbol} has "
                        f"{len(symbol_snapshot.adjusted_bars)} sessions; requires "
                        f"{MINIMUM_HISTORY_SESSIONS}"
                    ),
                )
            )
    anomalies = sorted(
        anomalies,
        key=lambda anomaly: (anomaly.symbol, anomaly.kind, anomaly.detail),
    )
    anomalies_tuple = tuple(anomalies)
    if not common and symbol_snapshots:
        anomalies_tuple = (
            *anomalies_tuple,
            YahooDataAnomaly("_global", "common_dates", "no common trading date"),
        )
    if not common and not symbol_snapshots:
        anomalies_tuple = (
            *anomalies_tuple,
            YahooDataAnomaly("_global", "snapshot", "no symbols were successfully snapshotted"),
        )
    return YahooSnapshotReport(
        symbol_snapshots=tuple(symbol_snapshots),
        common_trading_dates=common,
        anomalies=anomalies_tuple,
    )


def persist_yahoo_universe_report(report: YahooSnapshotReport, data_root: Path) -> Path:
    """Persist the fixed-universe coverage report beside its content-addressed snapshots."""
    root = _require_yahoo_data_root(data_root)
    payload = {
        "report_id": report.identity_sha256,
        "usage_level": RESEARCH_ADJUSTED_ONLY,
        "manifests": [item.manifest.manifest_id for item in report.symbol_snapshots],
        "common_trading_dates": [item.isoformat() for item in report.common_trading_dates],
        "anomalies": [item.__dict__ for item in report.anomalies],
    }
    path = root / "reports" / f"{report.identity_sha256}.json"
    write_immutable(path, _canonical_json_bytes(payload))
    return path


def load_yahoo_universe_report(path: Path) -> YahooSnapshotReport:
    """Reconstruct one immutable Yahoo research report without fetching a provider."""
    root = _require_yahoo_data_root(path.parents[2])
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        manifest_ids = tuple(str(item) for item in payload["manifests"])
        common_dates = tuple(date.fromisoformat(item) for item in payload["common_trading_dates"])
    except (KeyError, TypeError, ValueError, json.JSONDecodeError) as error:
        raise YahooProviderError("Yahoo universe report has invalid schema") from error
    if payload.get("usage_level") != RESEARCH_ADJUSTED_ONLY:
        raise YahooProviderError("Yahoo universe report has an invalid usage level")
    expected_id = str(payload.get("report_id", ""))
    if path.stem != expected_id:
        raise YahooProviderError(
            "Yahoo universe report filename differs from its declared identity"
        )
    snapshots: list[YahooSymbolSnapshot] = []
    for manifest_id in manifest_ids:
        candidates = tuple(root.glob(f"*/manifests/{manifest_id}.json"))
        if len(candidates) != 1:
            raise YahooProviderError(
                "Yahoo universe report references a missing or ambiguous manifest"
            )
        snapshots.append(_load_yahoo_symbol_snapshot(candidates[0], root))
    report = YahooSnapshotReport(
        symbol_snapshots=tuple(snapshots),
        common_trading_dates=common_dates,
        anomalies=tuple(
            YahooDataAnomaly(str(item["symbol"]), str(item["kind"]), str(item["detail"]))
            for item in payload.get("anomalies", [])
        ),
    )
    if report.identity_sha256 != expected_id:
        raise YahooProviderError("Yahoo universe report content identity does not verify")
    return report


def _load_yahoo_symbol_snapshot(path: Path, root: Path) -> YahooSymbolSnapshot:
    """Load one manifest and normalized adjusted-price file under the same snapshot root."""
    try:
        manifest_payload = json.loads(path.read_text(encoding="utf-8"))
        raw_file_payload = manifest_payload["raw_file"]
        normalized_file_payload = manifest_payload["normalized_file"]
        manifest = YahooProviderManifest(
            symbol=str(manifest_payload["symbol"]),
            manifest_id=str(manifest_payload["manifest_id"]),
            source_url=str(manifest_payload["source_url"]),
            canonical_request=str(manifest_payload["canonical_request"]),
            request_parameters={
                str(key): str(value)
                for key, value in manifest_payload["request_parameters"].items()
            },
            adapter_version=str(manifest_payload["adapter_version"]),
            retrieved_at=datetime.fromisoformat(str(manifest_payload["retrieved_at"])),
            http_metadata={
                str(key): str(value) for key, value in manifest_payload["http_metadata"].items()
            },
            raw_file=ManifestFile(**raw_file_payload),
            normalized_file=ManifestFile(**normalized_file_payload),
            row_count=int(manifest_payload["row_count"]),
            event_count=int(manifest_payload["event_count"]),
            first_trading_date=date.fromisoformat(str(manifest_payload["first_trading_date"])),
            last_trading_date=date.fromisoformat(str(manifest_payload["last_trading_date"])),
            raw_sha256=str(manifest_payload["raw_sha256"]),
        )
        normalized_path = root / manifest.normalized_file.relative_path
        normalized_bytes = normalized_path.read_bytes()
        normalized_payload = json.loads(normalized_bytes)
    except (KeyError, TypeError, ValueError, OSError, json.JSONDecodeError) as error:
        raise YahooProviderError("Yahoo symbol snapshot has invalid immutable artifacts") from error
    if _sha256(normalized_bytes) != manifest.normalized_file.sha256:
        raise YahooProviderError("Yahoo normalized artifact SHA-256 mismatch")
    bars = tuple(
        YahooAdjustedClose(
            manifest.symbol,
            date.fromisoformat(str(item["trading_date"])),
            Decimal(str(item["adjusted_close"])),
        )
        for item in normalized_payload.get("adjusted_close", [])
    )
    events = tuple(
        YahooCorporateAction(
            manifest.symbol,
            date.fromisoformat(str(item["trading_date"])),
            str(item["type"]),
            Decimal(str(item["value"])),
        )
        for item in normalized_payload.get("events", [])
    )
    anomalies = tuple(
        YahooDataAnomaly(str(item["symbol"]), str(item["kind"]), str(item["detail"]))
        for item in normalized_payload.get("anomalies", [])
    )
    if len(bars) != manifest.row_count or len(events) != manifest.event_count:
        raise YahooProviderError("Yahoo normalized artifact row counts differ from its manifest")
    return YahooSymbolSnapshot(
        manifest=manifest,
        adjusted_bars=bars,
        events=events,
        anomalies=anomalies,
    )


def persist_yahoo_symbol_snapshot(
    payload: YahooFetchPayload,
    adjusted: tuple[YahooAdjustedClose, ...],
    events: tuple[YahooCorporateAction, ...],
    anomalies: tuple[YahooDataAnomaly, ...],
    data_root: Path,
) -> YahooSymbolSnapshot:
    """Persist one symbol payload and parsed series as content-addressed immutable artifacts."""
    if not adjusted:
        raise YahooProviderError(f"no adjusted bars parsed for {payload.symbol}")
    root = _require_yahoo_data_root(data_root)
    raw_relative = Path(payload.raw_sha256) / "raw" / "response.json"
    raw_path = root / raw_relative
    write_immutable(raw_path, payload.raw_bytes)
    raw_file = ManifestFile(
        relative_path=raw_relative.as_posix(),
        sha256=payload.raw_sha256,
        size_bytes=len(payload.raw_bytes),
    )
    normalized_payload = {
        "symbol": payload.symbol,
        "request_url": payload.source_url,
        "canonical_request": payload.canonical_request,
        "request_parameters": payload.request_parameters,
        "retrieved_at": payload.retrieved_at.isoformat(),
        "adapter_version": payload.adapter_version,
        "http_metadata": payload.http_metadata,
        "row_count": len(adjusted),
        "event_count": len(events),
        "raw_sha256": payload.raw_sha256,
        "adjusted_close": [
            {
                "trading_date": bar.trading_date.isoformat(),
                "adjusted_close": str(bar.adjusted_close),
            }
            for bar in adjusted
        ],
        "events": [
            {
                "trading_date": event.trading_date.isoformat(),
                "type": event.event_type,
                "value": str(event.value),
            }
            for event in events
        ],
        "anomalies": [
            {"symbol": anomaly.symbol, "kind": anomaly.kind, "detail": anomaly.detail}
            for anomaly in anomalies
        ],
        "usage_level": RESEARCH_ADJUSTED_ONLY,
    }
    normalized_bytes = _canonical_json_bytes(normalized_payload)
    normalized_sha256 = _sha256(normalized_bytes)
    normalized_relative = Path(payload.raw_sha256) / "normalized" / f"{normalized_sha256}.json"
    normalized_path = root / normalized_relative
    write_immutable(normalized_path, normalized_bytes)
    manifest_id = _manifest_id(
        payload,
        raw_file.relative_path,
        normalized_relative.as_posix(),
        len(adjusted),
        len(events),
    )
    manifest_relative = Path(payload.raw_sha256) / "manifests" / f"{manifest_id}.json"
    manifest_path = root / manifest_relative
    normalized_first = adjusted[0].trading_date
    normalized_last = adjusted[-1].trading_date
    manifest = YahooProviderManifest(
        symbol=payload.symbol,
        manifest_id=manifest_id,
        source_url=payload.source_url,
        canonical_request=payload.canonical_request,
        request_parameters=payload.request_parameters,
        adapter_version=payload.adapter_version,
        retrieved_at=payload.retrieved_at,
        http_metadata=payload.http_metadata,
        raw_file=raw_file,
        normalized_file=ManifestFile(
            relative_path=normalized_relative.as_posix(),
            sha256=normalized_sha256,
            size_bytes=len(normalized_bytes),
        ),
        row_count=len(adjusted),
        event_count=len(events),
        first_trading_date=normalized_first,
        last_trading_date=normalized_last,
        raw_sha256=payload.raw_sha256,
    )
    write_immutable(manifest_path, _manifest_json_bytes(manifest))
    return YahooSymbolSnapshot(
        manifest=manifest,
        adjusted_bars=adjusted,
        events=events,
        anomalies=anomalies,
    )


def parse_yahoo_payload(
    payload: YahooFetchPayload,
) -> tuple[
    tuple[YahooAdjustedClose, ...],
    tuple[YahooCorporateAction, ...],
    tuple[YahooDataAnomaly, ...],
]:
    """Parse Yahoo adjusted closes and dividend/split events from one response."""
    try:
        raw = json.loads(payload.raw_bytes.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise YahooProviderError("Yahoo response is not valid JSON") from error
    charts = raw.get("chart")
    if not isinstance(charts, dict):
        raise YahooProviderError("Yahoo response missing chart object")
    results = charts.get("result")
    if not isinstance(results, list) or not results:
        response_error = charts.get("error")
        if response_error:
            raise YahooProviderError(f"Yahoo chart API returned error: {response_error}")
        raise YahooProviderError("Yahoo chart response contains no result series")
    series = results[0]
    if not isinstance(series, dict):
        raise YahooProviderError("Yahoo chart series has unexpected shape")
    timestamps = series.get("timestamp")
    indicators = series.get("indicators", {})
    if not isinstance(indicators, dict):
        raise YahooProviderError("Yahoo chart indicators missing")
    adjclose = indicators.get("adjclose")
    if (
        not isinstance(timestamps, list)
        or not isinstance(adjclose, list)
        or not adjclose
        or not isinstance(adjclose[0], dict)
    ):
        raise YahooProviderError("Yahoo chart payload missing adjusted-close history")
    adjusted_values = adjclose[0].get("adjclose")
    if not isinstance(adjusted_values, list):
        raise YahooProviderError("Yahoo adjusted-close payload has unexpected type")
    if len(timestamps) != len(adjusted_values):
        raise YahooProviderError("Yahoo payload has mismatched timestamp/value lengths")
    bars: list[YahooAdjustedClose] = []
    anomalies: list[YahooDataAnomaly] = []
    for session_index, close_raw in enumerate(adjusted_values):
        trading_date = _parse_timestamp_to_date(
            timestamps[session_index], payload.symbol, anomalies
        )
        if trading_date is None:
            continue
        if close_raw is None:
            anomalies.append(
                YahooDataAnomaly(
                    payload.symbol,
                    "missing_adjusted_close",
                    f"{payload.symbol} missing adjusted close at {trading_date.isoformat()}",
                )
            )
            continue
        adjusted_close = _parse_decimal(close_raw, payload.symbol, trading_date, anomalies)
        if adjusted_close is None:
            continue
        if adjusted_close <= 0:
            anomalies.append(
                YahooDataAnomaly(
                    payload.symbol,
                    "invalid_adjusted_close",
                    (
                        f"{payload.symbol} adjusted close is non-positive at "
                        f"{trading_date.isoformat()}"
                    ),
                )
            )
            continue
        bars.append(YahooAdjustedClose(payload.symbol, trading_date, adjusted_close))
    events = _parse_events(payload.symbol, series, anomalies)
    parsed_days = sorted({item.trading_date for item in bars})
    duplicated_days = len(parsed_days) != len(bars)
    if duplicated_days:
        anomalies.append(
            YahooDataAnomaly(
                payload.symbol,
                "duplicate_session",
                f"{payload.symbol} has duplicated trading sessions",
            )
        )
    bars_sorted = tuple(sorted(bars, key=lambda item: item.trading_date))
    return (
        bars_sorted,
        _dedupe_sorted_events(tuple(sorted(events, key=lambda event: event.trading_date))),
        tuple(anomalies),
    )


def _parse_events(
    symbol: str,
    series: dict[str, Any],
    anomalies: list[YahooDataAnomaly],
) -> list[YahooCorporateAction]:
    """Convert Yahoo dividend/split event objects to typed events."""
    events: list[YahooCorporateAction] = []
    raw_events = series.get("events")
    if not isinstance(raw_events, dict):
        return events
    for event_type, key in (("dividend", "dividends"), ("split", "splits")):
        raw_block = raw_events.get(key)
        if not isinstance(raw_block, dict):
            continue
        for _, details in raw_block.items():
            if not isinstance(details, dict):
                continue
            raw_date = details.get("date", _extract_event_date(details))
            trading_date = _coerce_date(raw_date, symbol, anomalies, f"{key}_event")
            if trading_date is None:
                continue
            if event_type == "split":
                numerator = details.get("numerator")
                denominator = details.get("denominator")
                if denominator in (None, 0, "0"):
                    anomalies.append(
                        YahooDataAnomaly(
                            symbol,
                            "invalid_split_event",
                            f"{symbol} split event missing valid denominator",
                        )
                    )
                    continue
                value = _safe_divide(
                    numerator,
                    denominator,
                    symbol,
                    anomalies,
                    "split_ratio",
                    symbol,
                )
                if value is None:
                    continue
            else:
                amount = details.get("amount")
                value = _safe_decimal(
                    amount,
                    symbol,
                    trading_date,
                    anomalies,
                    f"{event_type}_event",
                )
                if value is None:
                    continue
            events.append(YahooCorporateAction(symbol, trading_date, event_type, value))
    return events


def _extract_event_date(details: dict[str, Any]) -> int | str | None:
    """Best-effort fallback when Yahoo event date is not nested as ``date``."""
    for key in ("date", "time", "timestamp", "payableDate", "recordDate"):
        candidate = details.get(key)
        if isinstance(candidate, (int, str)):
            return candidate
    return None


def _coerce_date(
    raw_date: object,
    symbol: str,
    anomalies: list[YahooDataAnomaly],
    kind: str,
) -> date | None:
    """Resolve one event date with anomaly tracking."""
    if isinstance(raw_date, str):
        try:
            return date.fromisoformat(raw_date)
        except ValueError:
            pass
    if isinstance(raw_date, int):
        return _parse_timestamp_to_date(raw_date, symbol, anomalies)
    anomalies.append(
        YahooDataAnomaly(
            symbol,
            "invalid_event_date",
            f"{symbol} has non-normalized {kind} date: {raw_date!r}",
        )
    )
    return None


def _parse_timestamp_to_date(
    raw_timestamp: object,
    symbol: str,
    anomalies: list[YahooDataAnomaly],
) -> date | None:
    """Parse seconds-based Unix timestamps into exchange-local dates."""
    if not isinstance(raw_timestamp, (int, float)):
        anomalies.append(
            YahooDataAnomaly(
                symbol,
                "invalid_timestamp",
                f"{symbol} has invalid timestamp: {raw_timestamp!r}",
            )
        )
        return None
    if raw_timestamp <= 0:
        anomalies.append(
            YahooDataAnomaly(
                symbol,
                "invalid_timestamp",
                f"{symbol} has non-positive timestamp: {raw_timestamp}",
            )
        )
        return None
    return datetime.fromtimestamp(raw_timestamp, tz=UTC).date()


def _parse_decimal(
    raw_value: object,
    symbol: str,
    trading_date: date,
    anomalies: list[YahooDataAnomaly],
) -> Decimal | None:
    """Parse one numeric value into Decimal while collecting anomalies."""
    try:
        return Decimal(str(raw_value))
    except (InvalidOperation, TypeError, ValueError):
        anomalies.append(
            YahooDataAnomaly(
                symbol,
                "invalid_value",
                (
                    f"{symbol} has non-numeric adjusted close at "
                    f"{trading_date.isoformat()}: {raw_value!r}"
                ),
            )
        )
        return None


def _safe_decimal(
    raw_value: object,
    symbol: str,
    trading_date: date,
    anomalies: list[YahooDataAnomaly],
    context: str,
) -> Decimal | None:
    """Parse one event scalar to Decimal and enforce positivity."""
    value = _parse_decimal(raw_value, symbol, trading_date, anomalies)
    if value is None:
        return None
    if value <= 0:
        anomalies.append(
            YahooDataAnomaly(
                symbol,
                "invalid_event_value",
                f"{symbol} has non-positive {context}: {value}",
            )
        )
        return None
    return value


def _safe_divide(
    numerator_raw: object,
    denominator_raw: object,
    symbol: str,
    anomalies: list[YahooDataAnomaly],
    field: str,
    context: str,
) -> Decimal | None:
    """Safely compute split ratio and report malformed factor details."""
    # denominator can be zero-like string in some malformed fixtures
    if denominator_raw in (0, 0.0, "0", "0.0"):
        anomalies.append(
            YahooDataAnomaly(
                symbol,
                "invalid_split_ratio",
                f"{context} has non-positive denominator: {denominator_raw!r}",
            )
        )
        return None
    context_symbol = symbol
    date_marker = date(1970, 1, 1)
    numerator = _parse_decimal(numerator_raw, context_symbol, date_marker, anomalies)
    denominator = _parse_decimal(denominator_raw, context_symbol, date_marker, anomalies)
    if numerator is None or denominator is None:
        return None
    if denominator <= 0:
        anomalies.append(
            YahooDataAnomaly(
                symbol,
                "invalid_split_ratio",
                f"{symbol} split has non-positive denominator: {denominator}",
            )
        )
        return None
    ratio = numerator / denominator
    if ratio <= 0:
        anomalies.append(
            YahooDataAnomaly(
                symbol,
                "invalid_split_ratio",
                f"{symbol} split ratio is non-positive: {ratio}",
            )
        )
        return None
    return ratio


def _manifest_id(
    payload: YahooFetchPayload,
    raw_relative_path: str,
    normalized_relative_path: str,
    row_count: int,
    event_count: int,
) -> str:
    """Derive a stable manifest identity from immutable content inputs."""
    return _sha256(
        _canonical_json_bytes(
            {
                "adapter_version": payload.adapter_version,
                "symbol": payload.symbol,
                "source_url": payload.source_url,
                "request_parameters": payload.request_parameters,
                "raw_sha256": payload.raw_sha256,
                "raw_relative_path": raw_relative_path,
                "normalized_relative_path": normalized_relative_path,
                "row_count": row_count,
                "event_count": event_count,
                "usage_level": RESEARCH_ADJUSTED_ONLY,
            }
        )
    )


def _manifest_json_bytes(manifest: YahooProviderManifest) -> bytes:
    """Serialize one manifest in deterministic json form."""
    return _canonical_json_bytes(
        {
            "manifest_id": manifest.manifest_id,
            "symbol": manifest.symbol,
            "source_url": manifest.source_url,
            "canonical_request": manifest.canonical_request,
            "request_parameters": manifest.request_parameters,
            "adapter_version": manifest.adapter_version,
            "retrieved_at": manifest.retrieved_at.isoformat(),
            "http_metadata": manifest.http_metadata,
            "raw_file": manifest.raw_file.model_dump(mode="json"),
            "normalized_file": manifest.normalized_file.model_dump(mode="json"),
            "row_count": manifest.row_count,
            "event_count": manifest.event_count,
            "first_trading_date": manifest.first_trading_date.isoformat(),
            "last_trading_date": manifest.last_trading_date.isoformat(),
            "raw_sha256": manifest.raw_sha256,
            "usage_level": RESEARCH_ADJUSTED_ONLY,
        }
    )


def _canonical_json_bytes(value: object) -> bytes:
    """Serialize to compact, deterministic UTF-8 for hashing or storage."""
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode(
        "utf-8"
    )


def _sha256(content: bytes) -> str:
    """Return SHA-256 digest for immutable identity."""
    return sha256(content).hexdigest()


def _dedupe_sorted_events(
    events: tuple[YahooCorporateAction, ...],
) -> tuple[YahooCorporateAction, ...]:
    """Drop duplicate events deterministically while preserving sorted output."""
    seen: set[tuple[str, date, str, str]] = set()
    deduped: list[YahooCorporateAction] = []
    for event in sorted(
        events,
        key=lambda item: (item.trading_date, item.event_type, str(item.value)),
    ):
        key = (
            event.symbol,
            event.trading_date,
            event.event_type,
            str(event.value),
        )
        if key in seen:
            continue
        seen.add(key)
        deduped.append(event)
    return tuple(deduped)


def _build_request(symbol: str, as_of: date) -> tuple[str, str, dict[str, str]]:
    """Build sorted query and canonical request for a Yahoo chart query."""
    query = {
        "events": "div,split",
        "interval": "1d",
        "includeAdjustedClose": "true",
        "period1": "0",
        "period2": str(
            int(datetime.combine(as_of + timedelta(days=1), time.min, tzinfo=UTC).timestamp())
        ),
    }
    canonical_request = urlencode(sorted(query.items()), safe=",")
    encoded = quote(symbol)
    return (
        YAHOO_HISTORY_URL_TEMPLATE.format(symbol=encoded, query=canonical_request),
        canonical_request,
        query,
    )


def _require_yahoo_data_root(data_root: Path) -> Path:
    """Keep Yahoo research snapshots inside the dedicated V2 external-data namespace."""
    resolved = data_root.resolve()
    repository_data = REPOSITORY_ROOT / "data"
    if resolved.is_relative_to(repository_data) and resolved != repository_data / "external":
        raise YahooProviderError("Yahoo snapshots must not be nested in a V1 data namespace")
    if resolved.is_relative_to(REPOSITORY_ROOT) and resolved != repository_data / "external":
        raise YahooProviderError("Yahoo snapshots require the repository data/external root")
    if resolved == SEALED_EXTERNAL_ROOT:
        return resolved / YAHOO_DATASET_ID
    if resolved.name != "external" or resolved.parent.name != "data":
        raise YahooProviderError("Yahoo V2 snapshots require a data/external root")
    return resolved / YAHOO_DATASET_ID


def trading_dates(snapshot: YahooSymbolSnapshot) -> tuple[date, ...]:
    """Compatibility helper for internal report assembly."""
    return tuple(item.trading_date for item in snapshot.adjusted_bars)
