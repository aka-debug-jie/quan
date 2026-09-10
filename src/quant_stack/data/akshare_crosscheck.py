"""Read an immutable AKShare raw ingest as a provider-native cross-check series."""

from __future__ import annotations

from datetime import UTC
from decimal import Decimal
from pathlib import Path

import pyarrow.parquet as pq  # type: ignore[import-untyped]

from quant_stack.data.models import IngestionManifest, ProviderId, ProviderSeriesManifest
from quant_stack.models import DailyBar, Instrument, PriceBasis
from quant_stack.snapshot import write_immutable


def load_akshare_raw_crosscheck(
    manifest_path: Path, data_root: Path
) -> tuple[ProviderSeriesManifest, list[DailyBar]]:
    """Load one hash-verified raw AKShare ingest without changing its immutable source artifact."""
    ingest = IngestionManifest.model_validate_json(manifest_path.read_text(encoding="utf-8"))
    if ingest.request.price_basis is not PriceBasis.RAW:
        raise ValueError("cross-check requires an AKShare raw ingestion manifest")
    normalized_path = data_root / ingest.normalized_file.relative_path
    normalized_matches = (
        normalized_path.is_file()
        and _sha256(normalized_path.read_bytes()) == ingest.normalized_file.sha256
    )
    if not normalized_matches:
        raise ValueError("AKShare normalized artifact does not match its immutable manifest")
    provider_manifest = ProviderSeriesManifest(
        manifest_id=ingest.manifest_id,
        provider=ProviderId.AKSHARE_EASTMONEY,
        instrument=Instrument(
            symbol=ingest.request.instrument.symbol,
            exchange=ingest.request.instrument.exchange,
            currency=ingest.request.instrument.currency,
            asset_class=ingest.request.instrument.asset_class,
        ),
        price_basis=PriceBasis.RAW,
        volume_unit="lots",
        source_url="akshare://fund_etf_hist_em",
        retrieved_at=ingest.first_captured_at.astimezone(UTC),
        request_parameters={
            "symbol": ingest.request.instrument.symbol,
            "period": ingest.request.period,
            "start_date": ingest.request.start_date.isoformat(),
            "as_of_date": ingest.request.as_of_date.isoformat(),
        },
        http_metadata={},
        parser_version=ingest.adapter_version,
        normalization_version=ingest.adapter_version,
        raw_file=ingest.raw_file,
        normalized_file=ingest.normalized_file,
        row_count=ingest.row_count,
        first_trading_date=ingest.first_trading_date,
        last_trading_date=ingest.last_trading_date,
    )
    bars = [
        DailyBar(
            symbol=str(row["symbol"]),
            exchange=ingest.request.instrument.exchange,
            price_basis=PriceBasis.RAW,
            trading_date=row["trading_date"],
            open=Decimal(row["open"]),
            high=Decimal(row["high"]),
            low=Decimal(row["low"]),
            close=Decimal(row["close"]),
            volume=Decimal(row["volume"]),
        )
        for row in pq.read_table(normalized_path).to_pylist()
    ]
    return provider_manifest, bars


def write_crosscheck_manifest(manifest: ProviderSeriesManifest, path: Path) -> Path:
    """Persist the provider view separately when a D0 reconciliation needs its own receipt."""
    write_immutable(path, manifest.model_dump_json(indent=2).encode("utf-8") + b"\n")
    return path


def _sha256(content: bytes) -> str:
    """Return a lowercase SHA-256 digest for immutable-artifact verification."""
    from hashlib import sha256

    return sha256(content).hexdigest()
