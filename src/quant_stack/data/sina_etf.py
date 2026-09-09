"""Sina ETF raw-history provider kept independent from AKShare and SZSE series."""

from __future__ import annotations

import json
import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, date, datetime
from decimal import Decimal, InvalidOperation
from hashlib import sha256
from pathlib import Path
from typing import Any
from urllib.request import Request, urlopen

import pyarrow as pa  # type: ignore[import-untyped]
import pyarrow.parquet as pq  # type: ignore[import-untyped]
from akshare.stock.cons import hk_js_decode  # type: ignore[import-untyped]
from py_mini_racer import py_mini_racer  # type: ignore[import-untyped]

from quant_stack.data.models import ETFHistoryRequest, ProviderId, ProviderSeriesManifest
from quant_stack.models import DailyBar, Exchange, ManifestFile, PriceBasis
from quant_stack.snapshot import write_immutable
from quant_stack.validation import reject_duplicate_bars

SINA_HISTORY_URL_TEMPLATE = (
    "https://finance.sina.com.cn/realstock/company/{symbol}/hisdata_klc2/klc_kl.js"
)
SINA_ADJUSTMENT_URL_TEMPLATE = "https://finance.sina.com.cn/realstock/company/{symbol}/hfq.js"
SINA_PARSER_VERSION = "1.0.0"
SINA_NORMALIZATION_VERSION = "1.0.1"
SINA_MAX_ATTEMPTS = 3

SinaDecoder = Callable[[bytes], list[dict[str, Any]]]


class SinaProviderError(ValueError):
    """Raised when an independent Sina ETF response cannot be captured or normalized."""


@dataclass(frozen=True)
class SinaHistoryPayload:
    """One unmodified Sina response with its transport provenance."""

    source_url: str
    request_parameters: dict[str, str]
    http_metadata: dict[str, str]
    retrieved_at: datetime
    raw_bytes: bytes


def fetch_sina_etf_history(symbol: str) -> SinaHistoryPayload:
    """Fetch a Sina ETF history body with bounded retries and no provider blending."""
    normalized_symbol = _sina_symbol(symbol)
    source_url = SINA_HISTORY_URL_TEMPLATE.format(symbol=normalized_symbol)
    request = Request(source_url, headers={"User-Agent": "quant-stack-sina-provider/1.0"})
    last_error: OSError | None = None
    for attempt in range(SINA_MAX_ATTEMPTS):
        try:
            with urlopen(request, timeout=30) as response:
                raw_bytes = bytes(response.read())
                metadata = {key.lower(): value for key, value in response.headers.items()}
                metadata[":status"] = str(response.status)
            return SinaHistoryPayload(
                source_url=source_url,
                request_parameters={"symbol": normalized_symbol},
                http_metadata=metadata,
                retrieved_at=datetime.now(UTC),
                raw_bytes=raw_bytes,
            )
        except OSError as error:
            last_error = error
            if attempt + 1 < SINA_MAX_ATTEMPTS:
                time.sleep(0.2 * (attempt + 1))
    raise SinaProviderError(f"unable to fetch Sina ETF history: {source_url}") from last_error


def fetch_sina_adjustment_candidate(symbol: str) -> SinaHistoryPayload:
    """Capture Sina's adjustment-factor candidate as raw evidence, never as canonical prices."""
    normalized_symbol = _sina_symbol(symbol)
    source_url = SINA_ADJUSTMENT_URL_TEMPLATE.format(symbol=normalized_symbol)
    request = Request(source_url, headers={"User-Agent": "quant-stack-sina-provider/1.0"})
    try:
        with urlopen(request, timeout=30) as response:
            return SinaHistoryPayload(
                source_url=source_url,
                request_parameters={"symbol": normalized_symbol, "series": "hfq_candidate"},
                http_metadata={
                    **{key.lower(): value for key, value in response.headers.items()},
                    ":status": str(response.status),
                },
                retrieved_at=datetime.now(UTC),
                raw_bytes=bytes(response.read()),
            )
    except OSError as error:
        raise SinaProviderError(
            f"unable to fetch Sina adjustment candidate: {source_url}"
        ) from error


def persist_sina_adjustment_candidate(payload: SinaHistoryPayload, data_root: Path) -> Path:
    """Persist an unparsed candidate factor body and first retrieval metadata for verification."""
    digest = _sha256(payload.raw_bytes)
    path = data_root / "raw" / "sina_adjustment" / digest / "response.js"
    write_immutable(path, payload.raw_bytes)
    receipt = path.with_name("receipt.json")
    if not receipt.exists():
        write_immutable(
            receipt,
            _canonical_json(
                {
                    "source_url": payload.source_url,
                    "request_parameters": payload.request_parameters,
                    "http_metadata": payload.http_metadata,
                    "retrieved_at": payload.retrieved_at.isoformat(),
                    "sha256": digest,
                }
            )
            + b"\n",
        )
    return path


def parse_sina_etf_history(
    request: ETFHistoryRequest,
    payload: SinaHistoryPayload,
    decoder: SinaDecoder | None = None,
) -> list[DailyBar]:
    """Map a full Sina raw response to raw OHLCV without applying provider adjustments."""
    if request.instrument.exchange is not Exchange.SZSE:
        raise SinaProviderError(
            "Sina recovery provider is currently limited to the SZSE ETF target"
        )
    if request.price_basis is not PriceBasis.RAW:
        raise SinaProviderError("Sina recovery provider supplies raw daily bars only")
    rows = (decoder or _decode_sina_payload)(payload.raw_bytes)
    if not rows:
        raise SinaProviderError("Sina response contains no decoded daily rows")
    bars: list[DailyBar] = []
    for row in rows:
        trading_date = _parse_date(row.get("date"))
        if trading_date < request.start_date or trading_date > request.as_of_date:
            continue
        bars.append(
            DailyBar(
                symbol=request.instrument.symbol,
                exchange=request.instrument.exchange,
                price_basis=PriceBasis.RAW,
                trading_date=trading_date,
                open=_parse_decimal(row.get("open"), "open"),
                high=_parse_decimal(row.get("high"), "high"),
                low=_parse_decimal(row.get("low"), "low"),
                close=_parse_decimal(row.get("close"), "close"),
                volume=_parse_decimal(row.get("volume"), "volume"),
            )
        )
    if not bars:
        raise SinaProviderError("Sina response has no rows inside the requested range")
    reject_duplicate_bars(bars)
    return sorted(bars, key=lambda bar: bar.trading_date)


def persist_sina_etf_history(
    request: ETFHistoryRequest,
    payload: SinaHistoryPayload,
    data_root: Path,
    decoder: SinaDecoder | None = None,
) -> ProviderSeriesManifest:
    """Persist a provider-native Sina raw series, artifact hashes, and stable manifest identity."""
    bars = parse_sina_etf_history(request, payload, decoder)
    raw_sha256 = _sha256(payload.raw_bytes)
    raw_relative = Path("raw") / ProviderId.SINA.value / raw_sha256 / "response.js"
    write_immutable(data_root / raw_relative, payload.raw_bytes)
    raw_file = ManifestFile(
        relative_path=raw_relative.as_posix(), sha256=raw_sha256, size_bytes=len(payload.raw_bytes)
    )
    context_sha256 = _sha256(
        _canonical_json(
            {
                "provider": ProviderId.SINA.value,
                "source_url": payload.source_url,
                "request": request.model_dump(mode="json"),
                "raw_sha256": raw_sha256,
                "parser_version": SINA_PARSER_VERSION,
                "normalization_version": SINA_NORMALIZATION_VERSION,
            }
        )
    )
    normalized_bytes = _provider_parquet_bytes(bars, context_sha256)
    normalized_sha256 = _sha256(normalized_bytes)
    normalized_relative = (
        Path("normalized")
        / "providers"
        / ProviderId.SINA.value
        / request.instrument.exchange.value.lower()
        / request.instrument.symbol
        / PriceBasis.RAW.value
        / f"{normalized_sha256}.parquet"
    )
    write_immutable(data_root / normalized_relative, normalized_bytes)
    normalized_file = ManifestFile(
        relative_path=normalized_relative.as_posix(),
        sha256=normalized_sha256,
        size_bytes=len(normalized_bytes),
    )
    manifest_id = _sha256(
        _canonical_json(
            {
                "provider": ProviderId.SINA.value,
                "source_url": payload.source_url,
                "request": request.model_dump(mode="json"),
                "raw_file": raw_file.model_dump(mode="json"),
                "normalized_file": normalized_file.model_dump(mode="json"),
                "parser_version": SINA_PARSER_VERSION,
                "normalization_version": SINA_NORMALIZATION_VERSION,
            }
        )
    )
    manifest_path = data_root / "manifests" / "providers" / f"{manifest_id}.json"
    if manifest_path.is_file():
        return ProviderSeriesManifest.model_validate_json(manifest_path.read_text(encoding="utf-8"))
    manifest = ProviderSeriesManifest(
        manifest_id=manifest_id,
        provider=ProviderId.SINA,
        instrument=request.instrument,
        price_basis=PriceBasis.RAW,
        volume_unit="shares",
        source_url=payload.source_url,
        retrieved_at=payload.retrieved_at,
        request_parameters=payload.request_parameters,
        http_metadata=payload.http_metadata,
        parser_version=SINA_PARSER_VERSION,
        normalization_version=SINA_NORMALIZATION_VERSION,
        raw_file=raw_file,
        normalized_file=normalized_file,
        row_count=len(bars),
        first_trading_date=bars[0].trading_date,
        last_trading_date=bars[-1].trading_date,
    )
    write_immutable(manifest_path, manifest.model_dump_json(indent=2).encode("utf-8") + b"\n")
    return manifest


def load_sina_provider_bars(manifest: ProviderSeriesManifest, data_root: Path) -> list[DailyBar]:
    """Load a hash-verified provider-native Sina series without canonicalizing it."""
    if manifest.provider is not ProviderId.SINA:
        raise SinaProviderError("manifest is not a Sina provider series")
    path = data_root / manifest.normalized_file.relative_path
    if not path.is_file() or _sha256(path.read_bytes()) != manifest.normalized_file.sha256:
        raise SinaProviderError("Sina normalized provider artifact does not match its manifest")
    return [
        DailyBar(
            symbol=str(row["symbol"]),
            exchange=Exchange(str(row["exchange"])),
            price_basis=PriceBasis(str(row["price_basis"])),
            trading_date=row["trading_date"],
            open=Decimal(row["open"]),
            high=Decimal(row["high"]),
            low=Decimal(row["low"]),
            close=Decimal(row["close"]),
            volume=Decimal(row["volume"]),
        )
        for row in pq.read_table(path).to_pylist()
    ]


def _decode_sina_payload(raw_bytes: bytes) -> list[dict[str, Any]]:
    """Decode the provider's documented K-line payload without changing source content."""
    try:
        encoded = raw_bytes.decode("utf-8").split("=", maxsplit=1)[1].split(";", maxsplit=1)[0]
    except (IndexError, UnicodeDecodeError) as error:
        raise SinaProviderError("Sina response has no decodable K-line assignment") from error
    engine = py_mini_racer.MiniRacer()
    engine.eval(hk_js_decode)
    decoded = engine.call("d", encoded.replace('"', ""))
    if not isinstance(decoded, list) or any(not isinstance(item, dict) for item in decoded):
        raise SinaProviderError("Sina K-line decoder returned an unexpected shape")
    return decoded


def _sina_symbol(symbol: str) -> str:
    """Map a six-digit Shenzhen ETF code to Sina's provider-specific market symbol."""
    if len(symbol) != 6 or not symbol.isdigit():
        raise SinaProviderError("Sina ETF symbol must be a six-digit code")
    return f"sz{symbol}"


def _parse_date(value: Any) -> date:
    """Parse one provider trading date as an exchange-local date."""
    try:
        return date.fromisoformat(str(value).split("T", maxsplit=1)[0])
    except ValueError as error:
        raise SinaProviderError(f"invalid Sina trading date: {value!r}") from error


def _parse_decimal(value: Any, field: str) -> Decimal:
    """Parse one exact numeric provider field for DailyBar validation."""
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError) as error:
        raise SinaProviderError(f"invalid Sina {field}: {value!r}") from error


def _provider_parquet_bytes(bars: list[DailyBar], context_sha256: str) -> bytes:
    """Encode one provider-native series with a provenance fingerprint."""
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
            b"quant_stack.provider": ProviderId.SINA.value.encode("ascii"),
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


def _canonical_json(value: object) -> bytes:
    """Serialize provenance deterministically before hashing."""
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode(
        "utf-8"
    )


def _sha256(content: bytes) -> str:
    """Return a lowercase SHA-256 digest."""
    return sha256(content).hexdigest()
