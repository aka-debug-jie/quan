"""SSE official daily K-line provider used to adjudicate D0 raw disagreements."""

from __future__ import annotations

import json
import time
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from hashlib import sha256
from pathlib import Path
from urllib.parse import urlencode
from urllib.request import Request, urlopen

import pyarrow as pa  # type: ignore[import-untyped]
import pyarrow.parquet as pq  # type: ignore[import-untyped]

from quant_stack.data.models import ETFHistoryRequest, ProviderId, ProviderSeriesManifest
from quant_stack.data.sina_etf import SinaHistoryPayload
from quant_stack.models import DailyBar, Exchange, Instrument, ManifestFile, PriceBasis
from quant_stack.snapshot import write_immutable
from quant_stack.validation import reject_duplicate_bars

SSE_HISTORY_URL_TEMPLATE = "https://yunhq.sse.com.cn:32042/v1/sh1/dayk/{symbol}"
SSE_HISTORY_PARSER_VERSION = "1.0.1"
SSE_HISTORY_NORMALIZATION_VERSION = "1.0.0"


class SSEProviderError(ValueError):
    """Raised when an SSE official K-line response is unavailable or invalid."""


def fetch_sse_daily_history(symbol: str) -> SinaHistoryPayload:
    """Fetch the complete public SSE daily K-line response with bounded retries."""
    source_url = SSE_HISTORY_URL_TEMPLATE.format(symbol=symbol)
    parameters = {
        "begin": "-5000",
        "end": "-1",
        "period": "day",
        "select": "date,open,high,low,close,volume",
    }
    request = Request(
        f"{source_url}?{urlencode(parameters)}",
        headers={
            "Referer": "https://etf.sse.com.cn/",
            "User-Agent": "quant-stack-sse-provider/1.0",
        },
    )
    last_error: OSError | None = None
    for attempt in range(3):
        try:
            with urlopen(request, timeout=30) as response:
                return SinaHistoryPayload(
                    source_url=source_url,
                    request_parameters=parameters,
                    http_metadata={
                        **{key.lower(): value for key, value in response.headers.items()},
                        ":status": str(response.status),
                    },
                    retrieved_at=datetime.now(UTC),
                    raw_bytes=bytes(response.read()),
                )
        except OSError as error:
            last_error = error
            if attempt < 2:
                time.sleep(0.2 * (attempt + 1))
    raise SSEProviderError(f"unable to fetch SSE daily history: {symbol}") from last_error


def parse_sse_daily_history(
    request: ETFHistoryRequest, payload: SinaHistoryPayload
) -> list[DailyBar]:
    """Map one SSE response to raw bars without filling or adjusting observations."""
    if request.instrument.exchange is not Exchange.SSE or request.price_basis is not PriceBasis.RAW:
        raise SSEProviderError("SSE official history supports SSE raw ETF requests only")
    try:
        body = json.loads(payload.raw_bytes)
        rows = body["kline"]
        total = body["total"]
        response_symbol = body["code"]
    except (KeyError, TypeError, json.JSONDecodeError) as error:
        raise SSEProviderError("SSE history response has an unexpected shape") from error
    if response_symbol != request.instrument.symbol:
        raise SSEProviderError("SSE history response contains an unexpected security")
    if not isinstance(rows, list) or not isinstance(total, int) or len(rows) != total:
        raise SSEProviderError("SSE history response is not a complete series")
    bars: list[DailyBar] = []
    try:
        for row in rows:
            if not isinstance(row, list) or len(row) != 6:
                raise TypeError
            trading_date = datetime.strptime(str(row[0]), "%Y%m%d").date()
            if request.start_date <= trading_date <= request.as_of_date:
                bars.append(
                    DailyBar(
                        symbol=request.instrument.symbol,
                        exchange=Exchange.SSE,
                        price_basis=PriceBasis.RAW,
                        trading_date=trading_date,
                        open=Decimal(str(row[1])),
                        high=Decimal(str(row[2])),
                        low=Decimal(str(row[3])),
                        close=Decimal(str(row[4])),
                        volume=Decimal(str(row[5])),
                    )
                )
    except (TypeError, ValueError, InvalidOperation) as error:
        raise SSEProviderError("SSE history response contains invalid bar values") from error
    if not bars:
        raise SSEProviderError("SSE history response has no rows in the requested range")
    reject_duplicate_bars(bars)
    return sorted(bars, key=lambda bar: bar.trading_date)


def persist_sse_daily_history(
    request: ETFHistoryRequest, payload: SinaHistoryPayload, data_root: Path
) -> ProviderSeriesManifest:
    """Persist one immutable SSE response, normalized series, and provenance manifest."""
    bars = parse_sse_daily_history(request, payload)
    raw_sha256 = sha256(payload.raw_bytes).hexdigest()
    raw_relative = Path("raw") / ProviderId.SSE_OFFICIAL.value / raw_sha256 / "response.json"
    write_immutable(data_root / raw_relative, payload.raw_bytes)
    raw_file = ManifestFile(
        relative_path=raw_relative.as_posix(), sha256=raw_sha256, size_bytes=len(payload.raw_bytes)
    )
    context = _hash(
        _json_bytes(
            {
                "provider": ProviderId.SSE_OFFICIAL.value,
                "source_url": payload.source_url,
                "request": request.model_dump(mode="json"),
                "raw_sha256": raw_sha256,
                "parser_version": SSE_HISTORY_PARSER_VERSION,
                "normalization_version": SSE_HISTORY_NORMALIZATION_VERSION,
            }
        )
    )
    normalized_bytes = _parquet_bytes(bars, context)
    normalized_sha256 = _hash(normalized_bytes)
    normalized_relative = (
        Path("normalized")
        / "providers"
        / ProviderId.SSE_OFFICIAL.value
        / "sse"
        / request.instrument.symbol
        / "raw"
        / f"{normalized_sha256}.parquet"
    )
    write_immutable(data_root / normalized_relative, normalized_bytes)
    normalized_file = ManifestFile(
        relative_path=normalized_relative.as_posix(),
        sha256=normalized_sha256,
        size_bytes=len(normalized_bytes),
    )
    manifest_id = _hash(
        _json_bytes(
            {
                "provider": ProviderId.SSE_OFFICIAL.value,
                "source_url": payload.source_url,
                "request": request.model_dump(mode="json"),
                "raw_file": raw_file.model_dump(mode="json"),
                "normalized_file": normalized_file.model_dump(mode="json"),
                "parser_version": SSE_HISTORY_PARSER_VERSION,
                "normalization_version": SSE_HISTORY_NORMALIZATION_VERSION,
            }
        )
    )
    path = data_root / "manifests" / "providers" / f"{manifest_id}.json"
    if path.is_file():
        return ProviderSeriesManifest.model_validate_json(path.read_text(encoding="utf-8"))
    manifest = ProviderSeriesManifest(
        manifest_id=manifest_id,
        provider=ProviderId.SSE_OFFICIAL,
        instrument=Instrument(
            symbol=request.instrument.symbol,
            exchange=request.instrument.exchange,
            currency=request.instrument.currency,
            asset_class=request.instrument.asset_class,
        ),
        price_basis=PriceBasis.RAW,
        volume_unit="shares",
        source_url=payload.source_url,
        retrieved_at=payload.retrieved_at,
        request_parameters=payload.request_parameters,
        http_metadata=payload.http_metadata,
        parser_version=SSE_HISTORY_PARSER_VERSION,
        normalization_version=SSE_HISTORY_NORMALIZATION_VERSION,
        raw_file=raw_file,
        normalized_file=normalized_file,
        row_count=len(bars),
        first_trading_date=bars[0].trading_date,
        last_trading_date=bars[-1].trading_date,
    )
    write_immutable(path, manifest.model_dump_json(indent=2).encode("utf-8") + b"\n")
    return manifest


def load_sse_provider_bars(manifest: ProviderSeriesManifest, data_root: Path) -> list[DailyBar]:
    """Load a hash-verified SSE provider series."""
    if manifest.provider is not ProviderId.SSE_OFFICIAL:
        raise SSEProviderError("manifest is not an SSE official provider series")
    path = data_root / manifest.normalized_file.relative_path
    if not path.is_file() or _hash(path.read_bytes()) != manifest.normalized_file.sha256:
        raise SSEProviderError("SSE normalized provider artifact does not match its manifest")
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


def _parquet_bytes(bars: list[DailyBar], context: str) -> bytes:
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
            b"quant_stack.provider": b"sse_official",
            b"quant_stack.context_sha256": context.encode(),
        },
    )
    arrays = [
        pa.array([bar.symbol for bar in bars], type=pa.string()),
        pa.array([bar.exchange.value for bar in bars], type=pa.string()),
        pa.array([bar.price_basis.value for bar in bars], type=pa.string()),
        pa.array([bar.trading_date for bar in bars], type=pa.date32()),
        pa.array([bar.open for bar in bars], type=pa.decimal128(28, 10)),
        pa.array([bar.high for bar in bars], type=pa.decimal128(28, 10)),
        pa.array([bar.low for bar in bars], type=pa.decimal128(28, 10)),
        pa.array([bar.close for bar in bars], type=pa.decimal128(28, 10)),
        pa.array([bar.volume for bar in bars], type=pa.decimal128(28, 6)),
    ]
    output = pa.BufferOutputStream()
    pq.write_table(
        pa.Table.from_arrays(arrays, schema=schema),
        output,
        compression="zstd",
        use_dictionary=False,
    )
    return bytes(output.getvalue().to_pybytes())


def _json_bytes(value: object) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()


def _hash(content: bytes) -> str:
    return sha256(content).hexdigest()
