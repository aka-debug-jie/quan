"""SZSE official daily-quote provider kept independent from AKShare and canonical data."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, date, datetime
from decimal import Decimal, InvalidOperation
from hashlib import sha256
from pathlib import Path
from typing import Any
from urllib.parse import urlencode
from urllib.request import Request, urlopen

import pyarrow as pa  # type: ignore[import-untyped]
import pyarrow.parquet as pq  # type: ignore[import-untyped]

from quant_stack.data.models import ETFHistoryRequest, ProviderId, ProviderSeriesManifest
from quant_stack.models import DailyBar, Exchange, ManifestFile, PriceBasis
from quant_stack.snapshot import write_immutable
from quant_stack.validation import reject_duplicate_bars

SZSE_HISTORY_ENDPOINT = "https://www.szse.cn/api/market/ssjjhq/getHistoryData"
SZSE_PARSER_VERSION = "1.0.0"
SZSE_NORMALIZATION_VERSION = "1.0.0"


class SZSEProviderError(ValueError):
    """Raised when the official SZSE response cannot be fetched or parsed faithfully."""


@dataclass(frozen=True)
class SZSEHistoryPayload:
    """Official raw JSON response and its HTTP/request provenance."""

    source_url: str
    request_parameters: dict[str, str]
    http_metadata: dict[str, str]
    retrieved_at: datetime
    raw_bytes: bytes


def fetch_szse_daily_history(symbol: str) -> SZSEHistoryPayload:
    """Fetch one official SZSE daily-history response without canonicalizing it."""
    parameters = {"cycleType": "32", "marketId": "1", "code": symbol}
    source_url = f"{SZSE_HISTORY_ENDPOINT}?{urlencode(parameters)}"
    request = Request(source_url, headers={"User-Agent": "quant-stack-szse-provider/1.0"})
    try:
        with urlopen(request, timeout=30) as response:
            raw_bytes = bytes(response.read())
            metadata = {key.lower(): value for key, value in response.headers.items()}
            metadata[":status"] = str(response.status)
    except OSError as error:
        raise SZSEProviderError(f"unable to fetch SZSE history: {source_url}") from error
    return SZSEHistoryPayload(
        source_url=source_url,
        request_parameters=parameters,
        http_metadata=metadata,
        retrieved_at=datetime.now(UTC),
        raw_bytes=raw_bytes,
    )


def parse_szse_daily_history(
    request: ETFHistoryRequest,
    payload: SZSEHistoryPayload,
) -> list[DailyBar]:
    """Map official SZSE K-line arrays to raw daily bars without interpreting adjustments."""
    if request.instrument.exchange.value != "SZSE":
        raise SZSEProviderError("SZSE provider requires an SZSE instrument")
    if request.price_basis is not PriceBasis.RAW:
        raise SZSEProviderError("SZSE official provider supplies raw daily bars only")
    try:
        response = json.loads(payload.raw_bytes)
    except json.JSONDecodeError as error:
        raise SZSEProviderError("SZSE response is not valid JSON") from error
    if response.get("code") != "0" or not isinstance(response.get("data"), dict):
        raise SZSEProviderError(f"SZSE response reported failure: {response.get('message')!r}")
    rows = response["data"].get("picupdata")
    if not isinstance(rows, list) or not rows:
        raise SZSEProviderError("SZSE response contains no daily K-line rows")
    bars: list[DailyBar] = []
    for row in rows:
        if not isinstance(row, list) or len(row) < 9:
            raise SZSEProviderError("SZSE K-line row has an unexpected shape")
        trading_date = _parse_date(row[0])
        if trading_date < request.start_date or trading_date > request.as_of_date:
            continue
        bars.append(
            DailyBar(
                symbol=request.instrument.symbol,
                exchange=request.instrument.exchange,
                price_basis=PriceBasis.RAW,
                trading_date=trading_date,
                open=_parse_decimal(row[1], "open"),
                close=_parse_decimal(row[2], "close"),
                low=_parse_decimal(row[3], "low"),
                high=_parse_decimal(row[4], "high"),
                volume=_parse_decimal(row[7], "volume"),
            )
        )
    if not bars:
        raise SZSEProviderError("SZSE response has no rows inside the requested range")
    reject_duplicate_bars(bars)
    return sorted(bars, key=lambda bar: bar.trading_date)


def persist_szse_daily_history(
    request: ETFHistoryRequest,
    payload: SZSEHistoryPayload,
    data_root: Path,
) -> ProviderSeriesManifest:
    """Persist one provider-native SZSE raw series with request and HTTP provenance."""
    bars = parse_szse_daily_history(request, payload)
    raw_sha256 = _sha256(payload.raw_bytes)
    raw_relative = Path("raw") / ProviderId.SZSE_OFFICIAL.value / raw_sha256 / "response.json"
    raw_path = data_root / raw_relative
    write_immutable(raw_path, payload.raw_bytes)
    raw_file = ManifestFile(
        relative_path=raw_relative.as_posix(),
        sha256=raw_sha256,
        size_bytes=len(payload.raw_bytes),
    )
    context_sha256 = _sha256(
        _canonical_json(
            {
                "provider": ProviderId.SZSE_OFFICIAL.value,
                "source_url": payload.source_url,
                "request": request.model_dump(mode="json"),
                "raw_sha256": raw_sha256,
                "parser_version": SZSE_PARSER_VERSION,
                "normalization_version": SZSE_NORMALIZATION_VERSION,
            }
        )
    )
    normalized_bytes = _provider_parquet_bytes(bars, context_sha256)
    normalized_sha256 = _sha256(normalized_bytes)
    normalized_relative = (
        Path("normalized")
        / "providers"
        / ProviderId.SZSE_OFFICIAL.value
        / request.instrument.exchange.value.lower()
        / request.instrument.symbol
        / PriceBasis.RAW.value
        / f"{normalized_sha256}.parquet"
    )
    normalized_path = data_root / normalized_relative
    write_immutable(normalized_path, normalized_bytes)
    normalized_file = ManifestFile(
        relative_path=normalized_relative.as_posix(),
        sha256=normalized_sha256,
        size_bytes=len(normalized_bytes),
    )
    manifest_id = _sha256(
        _canonical_json(
            {
                "provider": ProviderId.SZSE_OFFICIAL.value,
                "source_url": payload.source_url,
                "request": request.model_dump(mode="json"),
                "raw_file": raw_file.model_dump(mode="json"),
                "normalized_file": normalized_file.model_dump(mode="json"),
                "parser_version": SZSE_PARSER_VERSION,
                "normalization_version": SZSE_NORMALIZATION_VERSION,
            }
        )
    )
    manifest_path = data_root / "manifests" / "providers" / f"{manifest_id}.json"
    if manifest_path.is_file():
        existing = ProviderSeriesManifest.model_validate_json(
            manifest_path.read_text(encoding="utf-8")
        )
        if existing.manifest_id != manifest_id:
            raise SZSEProviderError("existing SZSE manifest identity does not match its path")
        return existing
    manifest = ProviderSeriesManifest(
        manifest_id=manifest_id,
        provider=ProviderId.SZSE_OFFICIAL,
        instrument=request.instrument,
        price_basis=PriceBasis.RAW,
        source_url=payload.source_url,
        retrieved_at=payload.retrieved_at,
        request_parameters=payload.request_parameters,
        http_metadata=payload.http_metadata,
        parser_version=SZSE_PARSER_VERSION,
        normalization_version=SZSE_NORMALIZATION_VERSION,
        raw_file=raw_file,
        normalized_file=normalized_file,
        row_count=len(bars),
        first_trading_date=bars[0].trading_date,
        last_trading_date=bars[-1].trading_date,
    )
    write_immutable(manifest_path, manifest.model_dump_json(indent=2).encode("utf-8") + b"\n")
    return manifest


def load_szse_provider_bars(manifest: ProviderSeriesManifest, data_root: Path) -> list[DailyBar]:
    """Load a verified provider-native Parquet series without crossing into canonical data."""
    path = data_root / manifest.normalized_file.relative_path
    if not path.is_file() or _sha256(path.read_bytes()) != manifest.normalized_file.sha256:
        raise SZSEProviderError("SZSE normalized provider artifact does not match its manifest")
    table = pq.read_table(path)
    rows = table.to_pylist()
    return [
        DailyBar(
            symbol=str(row["symbol"]),
            exchange=request_exchange(row["exchange"]),
            price_basis=PriceBasis(str(row["price_basis"])),
            trading_date=row["trading_date"],
            open=Decimal(row["open"]),
            high=Decimal(row["high"]),
            low=Decimal(row["low"]),
            close=Decimal(row["close"]),
            volume=Decimal(row["volume"]),
        )
        for row in rows
    ]


def request_exchange(value: Any) -> Exchange:
    """Parse an exchange value while retaining the module's narrow provider contract."""
    return Exchange(str(value))


def _provider_parquet_bytes(bars: list[DailyBar], context_sha256: str) -> bytes:
    """Encode one provider-native series with an explicit provider-context fingerprint."""
    schema = pa.schema(
        [
            pa.field("symbol", pa.string(), nullable=False),
            pa.field("exchange", pa.string(), nullable=False),
            pa.field("price_basis", pa.string(), nullable=False),
            pa.field("trading_date", pa.date32(), nullable=False),
            pa.field("open", pa.decimal128(28, 10), nullable=False),
            pa.field("high", pa.decimal128(28, 10), nullable=False),
            pa.field("low", pa.decimal128(28, 10), nullable=False),
            pa.field("close", pa.decimal128(28, 10), nullable=False),
            pa.field("volume", pa.decimal128(28, 6), nullable=False),
        ],
        metadata={
            b"quant_stack.schema_version": b"1",
            b"quant_stack.provider": ProviderId.SZSE_OFFICIAL.value.encode("ascii"),
            b"quant_stack.context_sha256": context_sha256.encode("ascii"),
        },
    )
    table = pa.Table.from_arrays(
        [
            pa.array([bar.symbol for bar in bars], type=pa.string()),
            pa.array([bar.exchange.value for bar in bars], type=pa.string()),
            pa.array([bar.price_basis.value for bar in bars], type=pa.string()),
            pa.array([bar.trading_date for bar in bars], type=pa.date32()),
            pa.array([bar.open for bar in bars], type=pa.decimal128(28, 10)),
            pa.array([bar.high for bar in bars], type=pa.decimal128(28, 10)),
            pa.array([bar.low for bar in bars], type=pa.decimal128(28, 10)),
            pa.array([bar.close for bar in bars], type=pa.decimal128(28, 10)),
            pa.array([bar.volume for bar in bars], type=pa.decimal128(28, 6)),
        ],
        schema=schema,
    )
    output = pa.BufferOutputStream()
    pq.write_table(table, output, compression="zstd", use_dictionary=False)
    return bytes(output.getvalue().to_pybytes())


def _parse_date(value: Any) -> date:
    """Parse a provider date literal as an exchange-local date."""
    try:
        return date.fromisoformat(str(value))
    except ValueError as error:
        raise SZSEProviderError(f"invalid SZSE trading date: {value!r}") from error


def _parse_decimal(value: Any, field: str) -> Decimal:
    """Parse a numeric SZSE field without retaining binary floating-point semantics."""
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError) as error:
        raise SZSEProviderError(f"invalid SZSE {field}: {value!r}") from error


def _canonical_json(value: object) -> bytes:
    """Serialize provider provenance deterministically before hashing."""
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def _sha256(content: bytes) -> str:
    """Return a lowercase SHA-256 digest."""
    return sha256(content).hexdigest()
