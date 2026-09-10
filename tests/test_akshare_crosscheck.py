from datetime import UTC, date, datetime
from hashlib import sha256
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq

from quant_stack.data.akshare_crosscheck import load_akshare_raw_crosscheck
from quant_stack.data.models import ETFHistoryRequest, ETFUniverseInstrument, IngestionManifest
from quant_stack.models import Exchange, ManifestFile, PriceBasis


def test_loads_hash_verified_raw_ingest_as_lots_crosscheck_view(tmp_path: Path) -> None:
    normalized_path = tmp_path / "normalized.parquet"
    pq.write_table(
        pa.table(
            {
                "symbol": ["510300"],
                "trading_date": [date(2024, 1, 2)],
                "open": ["10"],
                "high": ["10"],
                "low": ["10"],
                "close": ["10"],
                "volume": ["1"],
            }
        ),
        normalized_path,
    )
    raw_path = tmp_path / "raw.csv"
    raw_path.write_bytes(b"provider export")
    digest = sha256(normalized_path.read_bytes()).hexdigest()
    manifest = IngestionManifest(
        manifest_id="a" * 64,
        provider="akshare",
        adapter_version="1",
        request=ETFHistoryRequest(
            instrument=ETFUniverseInstrument(
                symbol="510300", exchange=Exchange.SSE, effective_from=date(2015, 1, 1)
            ),
            start_date=date(2024, 1, 2),
            as_of_date=date(2024, 1, 2),
            price_basis=PriceBasis.RAW,
        ),
        first_captured_at=datetime(2024, 1, 3, tzinfo=UTC),
        raw_file=ManifestFile(
            relative_path="raw.csv",
            sha256=sha256(raw_path.read_bytes()).hexdigest(),
            size_bytes=15,
        ),
        normalized_file=ManifestFile(
            relative_path="normalized.parquet",
            sha256=digest,
            size_bytes=normalized_path.stat().st_size,
        ),
        row_count=1,
        first_trading_date=date(2024, 1, 2),
        last_trading_date=date(2024, 1, 2),
        calendar_sha256="b" * 64,
        coverage_complete=True,
    )
    manifest_path = tmp_path / "manifest.json"
    manifest_path.write_text(manifest.model_dump_json(), encoding="utf-8")
    provider, bars = load_akshare_raw_crosscheck(manifest_path, tmp_path)
    assert provider.provider.value == "akshare_eastmoney"
    assert provider.volume_unit == "lots"
    assert bars[0].symbol == "510300"
