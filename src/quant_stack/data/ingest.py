"""Immutable ETF ingestion transactions and local provenance verification."""

from __future__ import annotations

import json
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import UTC, date, datetime
from hashlib import sha256
from io import BytesIO
from pathlib import Path

import pandas as pd
import pyarrow as pa  # type: ignore[import-untyped]
import pyarrow.parquet as pq  # type: ignore[import-untyped]
import yaml

from quant_stack.data.akshare_etf import (
    ADAPTER_VERSION,
    AKShareETFAdapter,
    normalize_daily_bars,
    provider_export_bytes,
)
from quant_stack.data.calendar import ExchangeCalendarStore
from quant_stack.data.evidence import require_non_trading_evidence
from quant_stack.data.models import (
    LEGACY_CONTEXT_SHA256,
    CoverageReport,
    ETFHistoryRequest,
    ETFUniverse,
    ETFUniverseInstrument,
    IngestionManifest,
)
from quant_stack.models import DailyBar, ManifestFile, PriceBasis
from quant_stack.snapshot import write_immutable


class CoverageError(ValueError):
    """Raised when a data request leaves expected completed sessions uncovered."""


class ProvenanceError(ValueError):
    """Raised when a local Parquet file cannot be verified against an immutable manifest."""


@dataclass(frozen=True)
class IngestionResult:
    """Paths and provenance created by one immutable provider-export transaction."""

    manifest: IngestionManifest
    raw_path: Path
    normalized_path: Path
    manifest_path: Path
    coverage: CoverageReport


@dataclass(frozen=True)
class UniverseIngestionResult:
    """Results and final coverage reports for a versioned ETF universe run."""

    ingestions: tuple[IngestionResult, ...]
    coverage_reports: tuple[CoverageReport, ...]


def persist_provider_export(
    request: ETFHistoryRequest,
    provider_frame: pd.DataFrame,
    data_root: Path,
    calendar: ExchangeCalendarStore,
    *,
    captured_at: datetime | None = None,
    now: datetime | None = None,
) -> IngestionResult:
    """Persist a fetched provider export, normalized Parquet, and immutable provenance manifest."""
    raw_content = provider_export_bytes(provider_frame)
    return _persist_provider_export_content(
        request,
        provider_frame,
        raw_content,
        data_root,
        calendar,
        captured_at=captured_at,
        now=now,
    )


def reattest_existing_provider_export(
    request: ETFHistoryRequest,
    source_manifest: IngestionManifest,
    data_root: Path,
    calendar: ExchangeCalendarStore,
    *,
    captured_at: datetime | None = None,
    now: datetime | None = None,
) -> IngestionResult:
    """Create new V2 provenance from a retained provider export without contacting the provider."""
    raw_path = data_root / source_manifest.raw_file.relative_path
    if not raw_path.is_file():
        raise ProvenanceError(f"source provider export does not exist: {raw_path}")
    raw_content = raw_path.read_bytes()
    if _sha256(raw_content) != source_manifest.raw_file.sha256:
        raise ProvenanceError("source provider export does not match its manifest")
    provider_frame = pd.read_csv(BytesIO(raw_content))
    return _persist_provider_export_content(
        request,
        provider_frame,
        raw_content,
        data_root,
        calendar,
        captured_at=captured_at,
        now=now,
    )


def _persist_provider_export_content(
    request: ETFHistoryRequest,
    provider_frame: pd.DataFrame,
    raw_content: bytes,
    data_root: Path,
    calendar: ExchangeCalendarStore,
    *,
    captured_at: datetime | None,
    now: datetime | None,
) -> IngestionResult:
    """Materialize one immutable normalized dataset from provider-export bytes."""
    raw_sha256 = _sha256(raw_content)
    raw_relative = Path("raw") / "akshare_etf" / raw_sha256 / "provider_export.csv"
    raw_path = data_root / raw_relative
    write_immutable(raw_path, raw_content)

    bars = normalize_daily_bars(request, provider_frame)
    coverage = calendar.coverage_report(
        request.instrument,
        request.price_basis,
        {bar.trading_date for bar in bars},
        request.start_date,
        request.as_of_date,
        documented_non_trading_events=request.instrument.documented_non_trading_events,
        now=now,
    )
    raw_file = ManifestFile(
        relative_path=raw_relative.as_posix(),
        sha256=raw_sha256,
        size_bytes=len(raw_content),
    )
    calendar_sha256 = calendar.fingerprint(
        request.instrument.exchange,
        request.start_date,
        request.as_of_date,
    )
    context_sha256 = _context_sha256(request, raw_file, calendar_sha256, coverage)
    normalized_content = _parquet_bytes(bars, context_sha256)
    normalized_sha256 = _sha256(normalized_content)
    normalized_relative = (
        Path("normalized")
        / "etf_daily"
        / request.instrument.exchange.value.lower()
        / request.instrument.symbol
        / request.price_basis.value
        / f"{normalized_sha256}.parquet"
    )
    normalized_path = data_root / normalized_relative
    write_immutable(normalized_path, normalized_content)
    normalized_file = ManifestFile(
        relative_path=normalized_relative.as_posix(),
        sha256=normalized_sha256,
        size_bytes=len(normalized_content),
    )
    manifest_id = _manifest_id(
        request,
        raw_file,
        normalized_file,
        len(bars),
        bars[0].trading_date,
        bars[-1].trading_date,
        calendar_sha256,
        context_sha256,
        coverage,
    )
    manifest_relative = Path("manifests") / f"{manifest_id}.json"
    manifest_path = data_root / manifest_relative
    if manifest_path.exists():
        manifest = IngestionManifest.model_validate_json(manifest_path.read_text(encoding="utf-8"))
        _validate_existing_manifest(
            manifest,
            manifest_id,
            raw_file,
            normalized_file,
            calendar_sha256,
            context_sha256,
        )
    else:
        manifest = IngestionManifest(
            manifest_id=manifest_id,
            provider="akshare",
            adapter_version=ADAPTER_VERSION,
            request=request,
            first_captured_at=captured_at or datetime.now(UTC),
            raw_file=raw_file,
            normalized_file=normalized_file,
            row_count=len(bars),
            first_trading_date=bars[0].trading_date,
            last_trading_date=bars[-1].trading_date,
            calendar_sha256=calendar_sha256,
            context_sha256=context_sha256,
            coverage_complete=coverage.is_complete,
            coverage_missing=coverage.missing,
            coverage_documented_non_trading=coverage.documented_non_trading,
        )
        write_immutable(
            manifest_path,
            manifest.model_dump_json(indent=2).encode("utf-8") + b"\n",
        )
    return IngestionResult(
        manifest=manifest,
        raw_path=raw_path,
        normalized_path=normalized_path,
        manifest_path=manifest_path,
        coverage=coverage,
    )


def ingest_universe(
    universe: ETFUniverse,
    start_date: date,
    as_of_date: date,
    data_root: Path,
    calendar: ExchangeCalendarStore,
    adapter: AKShareETFAdapter,
    *,
    now: datetime | None = None,
) -> UniverseIngestionResult:
    """Backfill only missing sessions, then enforce complete raw and qfq ETF coverage."""
    results: list[IngestionResult] = []
    reports: list[CoverageReport] = []
    for instrument in universe.instruments:
        if instrument.effective_from > as_of_date:
            continue
        bounded_start = max(start_date, instrument.effective_from)
        bounded_end = min(as_of_date, instrument.effective_to or as_of_date)
        calendar.require_completed_as_of(instrument.exchange, bounded_end, now)
        require_non_trading_evidence(instrument.documented_non_trading_events, data_root)
        calendar.require_source_archives(
            instrument.exchange,
            bounded_start,
            bounded_end,
            data_root,
        )
        documented_dates = {
            event_date
            for event in instrument.documented_non_trading_events
            for event_date in event.dates
        }
        request_start, request_end = _request_bounds(
            calendar,
            instrument.exchange.value,
            bounded_start,
            bounded_end,
            documented_dates,
        )
        for price_basis in (PriceBasis.RAW, PriceBasis.QFQ):
            existing_dates = normalized_dates(
                data_root,
                instrument.exchange.value,
                instrument.symbol,
                price_basis,
            )
            for range_start, range_end in missing_session_ranges(
                calendar,
                instrument.exchange.value,
                bounded_start,
                bounded_end,
                existing_dates,
                documented_dates,
            ):
                for chunk_start, chunk_end in split_request_range_by_calendar_year(
                    calendar,
                    instrument.exchange.value,
                    range_start,
                    range_end,
                ):
                    request = _history_request(
                        universe,
                        instrument,
                        chunk_start,
                        chunk_end,
                        price_basis,
                    )
                    results.append(
                        persist_provider_export(
                            request,
                            adapter.fetch(request),
                            data_root,
                            calendar,
                            now=now,
                        )
                    )
            if request_start is not None and request_end is not None:
                full_request = _history_request(
                    universe,
                    instrument,
                    request_start,
                    request_end,
                    price_basis,
                )
                if not _has_manifest_for_request(data_root, full_request):
                    source_manifest = _find_reusable_source_manifest(
                        data_root,
                        full_request,
                    )
                    if source_manifest is not None:
                        results.append(
                            reattest_existing_provider_export(
                                full_request,
                                source_manifest,
                                data_root,
                                calendar,
                                now=now,
                            )
                        )
            report = calendar.coverage_report(
                instrument,
                price_basis,
                normalized_dates(
                    data_root,
                    instrument.exchange.value,
                    instrument.symbol,
                    price_basis,
                ),
                bounded_start,
                bounded_end,
                documented_non_trading_events=instrument.documented_non_trading_events,
                now=now,
            )
            reports.append(report)
    if any(not report.is_complete for report in reports):
        raise CoverageError(_format_incomplete_reports(reports))
    return UniverseIngestionResult(ingestions=tuple(results), coverage_reports=tuple(reports))


def load_etf_universe(path: Path) -> ETFUniverse:
    """Load a versioned ETF universe YAML without contacting any external service."""
    if not path.is_file():
        raise ValueError(f"ETF universe file does not exist: {path}")
    loaded = yaml.safe_load(path.read_text(encoding="utf-8"))
    return ETFUniverse.model_validate(loaded)


def _history_request(
    universe: ETFUniverse,
    instrument: ETFUniverseInstrument,
    start_date: date,
    as_of_date: date,
    price_basis: PriceBasis,
) -> ETFHistoryRequest:
    """Bind an ETF history request to the versioned universe that selected the instrument."""
    return ETFHistoryRequest(
        instrument=instrument,
        universe_id=universe.universe_id,
        universe_version=universe.version,
        start_date=start_date,
        as_of_date=as_of_date,
        price_basis=price_basis,
    )


def _has_manifest_for_request(data_root: Path, request: ETFHistoryRequest) -> bool:
    """Return whether this exact universe, evidence, and time range already has a manifest."""
    return any(
        manifest.request == request
        for manifest in _load_manifests(data_root)
        if manifest.coverage_complete
    )


def _find_reusable_source_manifest(
    data_root: Path,
    request: ETFHistoryRequest,
) -> IngestionManifest | None:
    """Find a retained provider export that covers a new contextual attestation request."""
    candidates = [
        manifest
        for manifest in _load_manifests(data_root)
        if manifest.request.instrument.exchange is request.instrument.exchange
        and manifest.request.instrument.symbol == request.instrument.symbol
        and manifest.request.price_basis is request.price_basis
        and manifest.request.start_date <= request.start_date
        and manifest.request.as_of_date >= request.as_of_date
    ]
    if not candidates:
        return None
    return max(candidates, key=lambda manifest: manifest.first_captured_at)


def _load_manifests(data_root: Path) -> tuple[IngestionManifest, ...]:
    """Load all local manifests for provenance lookup without contacting a provider."""
    manifests_root = data_root / "manifests"
    if not manifests_root.is_dir():
        return ()
    return tuple(
        IngestionManifest.model_validate_json(path.read_text(encoding="utf-8"))
        for path in sorted(manifests_root.glob("*.json"))
    )


def normalized_dates(
    data_root: Path,
    exchange: str,
    symbol: str,
    price_basis: PriceBasis,
) -> set[date]:
    """Read dates only from normalized files that still verify against immutable provenance."""
    root = data_root / "normalized" / "etf_daily" / exchange.lower() / symbol / price_basis.value
    if not root.is_dir():
        return set()
    dates: set[date] = set()
    for path in sorted(root.glob("*.parquet")):
        verify_normalized_parquet(path, data_root)
        table = pq.read_table(path, columns=["trading_date"])
        dates.update(value.as_py() for value in table.column("trading_date"))
    return dates


def missing_session_ranges(
    calendar: ExchangeCalendarStore,
    exchange_name: str,
    start_date: date,
    end_date: date,
    present_dates: set[date],
    excluded_dates: set[date] | None = None,
) -> tuple[tuple[date, date], ...]:
    """Group uncovered explicit sessions into the smallest provider request intervals."""
    from quant_stack.models import Exchange

    exchange = Exchange(exchange_name)
    excluded = excluded_dates or set()
    missing = [
        session
        for session in calendar.sessions_between(exchange, start_date, end_date)
        if session not in present_dates and session not in excluded
    ]
    if not missing:
        return ()
    ranges: list[tuple[date, date]] = []
    range_start = missing[0]
    previous = missing[0]
    for current in missing[1:]:
        if calendar.next_session(exchange, previous) != current:
            ranges.append((range_start, previous))
            range_start = current
        previous = current
    ranges.append((range_start, previous))
    return tuple(ranges)


def _request_bounds(
    calendar: ExchangeCalendarStore,
    exchange_name: str,
    start_date: date,
    end_date: date,
    excluded_dates: set[date],
) -> tuple[date | None, date | None]:
    """Return the first and last provider-requestable sessions after documented exclusions."""
    from quant_stack.models import Exchange

    sessions = [
        session
        for session in calendar.sessions_between(Exchange(exchange_name), start_date, end_date)
        if session not in excluded_dates
    ]
    if not sessions:
        return None, None
    return sessions[0], sessions[-1]


def split_request_range_by_calendar_year(
    calendar: ExchangeCalendarStore,
    exchange_name: str,
    start_date: date,
    end_date: date,
) -> tuple[tuple[date, date], ...]:
    """Split a long provider request into inclusive calendar-year session ranges."""
    from quant_stack.models import Exchange

    exchange = Exchange(exchange_name)
    chunks: list[tuple[date, date]] = []
    for year in range(start_date.year, end_date.year + 1):
        year_start = max(start_date, date(year, 1, 1))
        year_end = min(end_date, date(year, 12, 31))
        sessions = calendar.sessions_between(exchange, year_start, year_end)
        if sessions:
            chunks.append((sessions[0], sessions[-1]))
    return tuple(chunks)


def verify_normalized_parquet(path: Path, data_root: Path) -> IngestionManifest:
    """Verify a normalized Parquet's hash and corresponding raw snapshot through its manifest."""
    if not path.is_file():
        raise ProvenanceError(f"normalized file does not exist: {path}")
    normalized_sha256 = _sha256(path.read_bytes())
    manifest = _find_manifest_for_normalized_file(data_root, normalized_sha256)
    expected_path = data_root / manifest.normalized_file.relative_path
    if path.resolve() != expected_path.resolve():
        raise ProvenanceError("normalized file path does not match its manifest")
    if expected_path.stat().st_size != manifest.normalized_file.size_bytes:
        raise ProvenanceError("normalized file size does not match its manifest")
    parquet_metadata = pq.read_metadata(path).metadata or {}
    stored_context = parquet_metadata.get(b"quant_stack.context_sha256")
    if (
        manifest.context_sha256 != LEGACY_CONTEXT_SHA256
        and stored_context != manifest.context_sha256.encode("ascii")
    ):
        raise ProvenanceError("normalized file context does not match its manifest")
    raw_path = data_root / manifest.raw_file.relative_path
    if not raw_path.is_file() or _sha256(raw_path.read_bytes()) != manifest.raw_file.sha256:
        raise ProvenanceError("raw source snapshot does not match its manifest")
    require_non_trading_evidence(
        manifest.request.instrument.documented_non_trading_events,
        data_root,
    )
    return manifest


def _find_manifest_for_normalized_file(
    data_root: Path,
    normalized_sha256: str,
) -> IngestionManifest:
    manifests_root = data_root / "manifests"
    if not manifests_root.is_dir():
        raise ProvenanceError("manifest directory does not exist")
    matches: list[IngestionManifest] = []
    for path in manifests_root.glob("*.json"):
        manifest = IngestionManifest.model_validate_json(path.read_text(encoding="utf-8"))
        if manifest.normalized_file.sha256 == normalized_sha256:
            matches.append(manifest)
    if len(matches) != 1:
        raise ProvenanceError("expected exactly one manifest for normalized file hash")
    return matches[0]


def _parquet_bytes(bars: Iterable[DailyBar], context_sha256: str) -> bytes:
    """Encode strict daily bars as a deterministic-schema Parquet payload."""
    rows = list(bars)
    if not rows:
        raise ValueError("cannot write an empty normalized dataset")
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
            b"quant_stack.context_sha256": context_sha256.encode("ascii"),
        },
    )
    table = pa.Table.from_arrays(
        [
            pa.array([bar.symbol for bar in rows], type=pa.string()),
            pa.array([bar.exchange.value for bar in rows], type=pa.string()),
            pa.array([bar.price_basis.value for bar in rows], type=pa.string()),
            pa.array([bar.trading_date for bar in rows], type=pa.date32()),
            pa.array([bar.open for bar in rows], type=pa.decimal128(28, 10)),
            pa.array([bar.high for bar in rows], type=pa.decimal128(28, 10)),
            pa.array([bar.low for bar in rows], type=pa.decimal128(28, 10)),
            pa.array([bar.close for bar in rows], type=pa.decimal128(28, 10)),
            pa.array([bar.volume for bar in rows], type=pa.decimal128(28, 6)),
        ],
        schema=schema,
    )
    output = pa.BufferOutputStream()
    pq.write_table(table, output, compression="zstd", use_dictionary=False)
    return bytes(output.getvalue().to_pybytes())


def _manifest_id(
    request: ETFHistoryRequest,
    raw_file: ManifestFile,
    normalized_file: ManifestFile,
    row_count: int,
    first_trading_date: date,
    last_trading_date: date,
    calendar_sha256: str,
    context_sha256: str,
    coverage: CoverageReport,
) -> str:
    """Hash stable request, content, and calendar identity without a runtime timestamp."""
    identity = {
        "provider": "akshare",
        "adapter_version": ADAPTER_VERSION,
        "request": request.model_dump(mode="json"),
        "raw_file": raw_file.model_dump(mode="json"),
        "normalized_file": normalized_file.model_dump(mode="json"),
        "row_count": row_count,
        "first_trading_date": first_trading_date.isoformat(),
        "last_trading_date": last_trading_date.isoformat(),
        "calendar_sha256": calendar_sha256,
        "context_sha256": context_sha256,
        "coverage_complete": coverage.is_complete,
        "coverage_missing": [record.model_dump(mode="json") for record in coverage.missing],
        "coverage_documented_non_trading": [
            record.model_dump(mode="json") for record in coverage.documented_non_trading
        ],
    }
    return _sha256(_canonical_json(identity))


def _validate_existing_manifest(
    manifest: IngestionManifest,
    manifest_id: str,
    raw_file: ManifestFile,
    normalized_file: ManifestFile,
    calendar_sha256: str,
    context_sha256: str,
) -> None:
    """Reject a manifest-path collision unless it represents exactly the same immutable output."""
    if (
        manifest.manifest_id != manifest_id
        or manifest.raw_file != raw_file
        or manifest.normalized_file != normalized_file
        or manifest.calendar_sha256 != calendar_sha256
        or manifest.context_sha256 != context_sha256
    ):
        raise ProvenanceError("existing manifest conflicts with immutable ingestion identity")


def _context_sha256(
    request: ETFHistoryRequest,
    raw_file: ManifestFile,
    calendar_sha256: str,
    coverage: CoverageReport,
) -> str:
    """Hash the universe and evidence context embedded in a normalized Parquet artifact."""
    identity = {
        "adapter_version": ADAPTER_VERSION,
        "request": request.model_dump(mode="json"),
        "raw_file": raw_file.model_dump(mode="json"),
        "calendar_sha256": calendar_sha256,
        "coverage_missing": [record.model_dump(mode="json") for record in coverage.missing],
        "coverage_documented_non_trading": [
            record.model_dump(mode="json") for record in coverage.documented_non_trading
        ],
    }
    return _sha256(_canonical_json(identity))


def _format_incomplete_reports(reports: Iterable[CoverageReport]) -> str:
    """Describe all unresolved expected-session gaps without silently accepting them."""
    gaps = [
        f"{report.instrument.exchange.value}:{report.instrument.symbol}:{report.price_basis.value}:"
        f"{record.trading_date.isoformat()}"
        for report in reports
        for record in report.missing
        if record.kind == "expected_session_missing"
    ]
    return "expected session data is missing: " + ", ".join(gaps)


def _canonical_json(value: object) -> bytes:
    """Serialize identity material deterministically before hashing."""
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def _sha256(content: bytes) -> str:
    """Return a lowercase SHA-256 digest for immutable content addressing."""
    return sha256(content).hexdigest()
