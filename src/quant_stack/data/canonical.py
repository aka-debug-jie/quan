"""Deterministic canonical raw/qfq construction from provider data and an action ledger."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from hashlib import sha256
from pathlib import Path

import pyarrow as pa  # type: ignore[import-untyped]
import pyarrow.parquet as pq  # type: ignore[import-untyped]

from quant_stack.data.evidence import require_corporate_action_evidence
from quant_stack.data.models import (
    CanonicalDatasetManifest,
    CorporateActionEvent,
    CorporateActionKind,
    CorporateActionLedger,
    ProviderSeriesManifest,
)
from quant_stack.models import DailyBar, ManifestFile, PriceBasis
from quant_stack.snapshot import write_immutable

CANONICAL_ALGORITHM_VERSION = "1.0.0"


class CanonicalizationError(ValueError):
    """Raised when a canonical raw/qfq dataset cannot be derived without guessing."""


@dataclass(frozen=True)
class AdjustmentFactor:
    """Deterministic multiplier applied to one raw daily bar when deriving qfq OHLC."""

    trading_date: date
    factor: Decimal


@dataclass(frozen=True)
class CanonicalizationResult:
    """Canonical raw/qfq output manifests created from one validated provider-native raw series."""

    raw_manifest: CanonicalDatasetManifest
    qfq_manifest: CanonicalDatasetManifest


def persist_canonical_raw_dataset(
    provider_manifest: ProviderSeriesManifest,
    raw_bars: list[DailyBar],
    data_root: Path,
) -> CanonicalDatasetManifest:
    """Publish a raw provider series without implying approval of any adjusted-price series."""
    if provider_manifest.price_basis is not PriceBasis.RAW:
        raise CanonicalizationError("canonical raw source manifest must contain raw prices")
    if not raw_bars:
        raise CanonicalizationError("cannot publish an empty canonical raw series")
    first = raw_bars[0]
    if any(
        bar.price_basis is not PriceBasis.RAW
        or bar.symbol != first.symbol
        or bar.exchange is not first.exchange
        for bar in raw_bars
    ):
        raise CanonicalizationError("canonical raw series mixes identities or price bases")
    if (
        first.symbol != provider_manifest.instrument.symbol
        or first.exchange is not provider_manifest.instrument.exchange
    ):
        raise CanonicalizationError("canonical raw bars do not match their provider manifest")
    if tuple(bar.trading_date for bar in raw_bars) != tuple(
        sorted(bar.trading_date for bar in raw_bars)
    ):
        raise CanonicalizationError("canonical raw bars must be ascending")
    return _persist_one_canonical_basis(
        provider_manifest,
        raw_bars,
        PriceBasis.RAW,
        data_root,
        corporate_action_ledger_id=None,
        adjustment_factors=(),
    )


def derive_qfq_bars(
    raw_bars: list[DailyBar],
    ledger: CorporateActionLedger,
) -> tuple[list[DailyBar], tuple[AdjustmentFactor, ...]]:
    """Derive qfq OHLC from raw bars and a complete official corporate-action ledger."""
    if ledger.completeness != "complete":
        raise CanonicalizationError("corporate-action ledger must be complete before deriving qfq")
    if not raw_bars:
        raise CanonicalizationError("cannot derive qfq from an empty raw series")
    _validate_raw_bars(raw_bars, ledger)
    bars = sorted(raw_bars, key=lambda bar: bar.trading_date)
    event_by_date = _events_by_application_date(bars, ledger)
    factors: dict[date, Decimal] = {}
    factor = Decimal("1")
    for index in range(len(bars) - 1, -1, -1):
        bar = bars[index]
        factors[bar.trading_date] = factor
        event = event_by_date.get(bar.trading_date)
        if event is None:
            continue
        if index == 0:
            raise CanonicalizationError("corporate action has no preceding raw close")
        previous_close = bars[index - 1].close
        if event.kind is CorporateActionKind.SHARE_SPLIT:
            assert event.split_ratio is not None
            factor /= event.split_ratio
        if event.kind is CorporateActionKind.CASH_DISTRIBUTION:
            assert event.cash_per_unit is not None
            if previous_close <= event.cash_per_unit:
                raise CanonicalizationError(
                    "cash distribution is not smaller than preceding raw close"
                )
            factor *= (previous_close - event.cash_per_unit) / previous_close
    qfq_bars = [
        DailyBar(
            symbol=bar.symbol,
            exchange=bar.exchange,
            price_basis=PriceBasis.QFQ,
            trading_date=bar.trading_date,
            open=bar.open * factors[bar.trading_date],
            high=bar.high * factors[bar.trading_date],
            low=bar.low * factors[bar.trading_date],
            close=bar.close * factors[bar.trading_date],
            volume=bar.volume,
        )
        for bar in bars
    ]
    return qfq_bars, tuple(
        AdjustmentFactor(trading_date=bar.trading_date, factor=factors[bar.trading_date])
        for bar in bars
    )


def validate_canonical_source(
    manifest: ProviderSeriesManifest,
    raw_bars: list[DailyBar],
    ledger: CorporateActionLedger,
) -> None:
    """Ensure canonicalization uses one raw provider series and its matching complete ledger."""
    if manifest.price_basis is not PriceBasis.RAW:
        raise CanonicalizationError("canonical source manifest must contain raw prices")
    if manifest.instrument != ledger.instrument:
        raise CanonicalizationError(
            "corporate-action ledger instrument does not match provider series"
        )
    _validate_raw_bars(raw_bars, ledger)


def persist_canonical_dataset(
    provider_manifest: ProviderSeriesManifest,
    raw_bars: list[DailyBar],
    ledger: CorporateActionLedger,
    data_root: Path,
) -> CanonicalizationResult:
    """Persist deterministic canonical raw and qfq datasets after source and ledger validation."""
    validate_canonical_source(provider_manifest, raw_bars, ledger)
    require_corporate_action_evidence(ledger.events, data_root)
    qfq_bars, factors = derive_qfq_bars(raw_bars, ledger)
    raw_manifest = _persist_one_canonical_basis(
        provider_manifest,
        raw_bars,
        PriceBasis.RAW,
        data_root,
        corporate_action_ledger_id=None,
        adjustment_factors=(),
    )
    qfq_manifest = _persist_one_canonical_basis(
        provider_manifest,
        qfq_bars,
        PriceBasis.QFQ,
        data_root,
        corporate_action_ledger_id=ledger.ledger_id,
        adjustment_factors=factors,
    )
    return CanonicalizationResult(raw_manifest=raw_manifest, qfq_manifest=qfq_manifest)


def _validate_raw_bars(raw_bars: list[DailyBar], ledger: CorporateActionLedger) -> None:
    """Reject mixed, unordered, duplicated, or non-raw bars before adjustment."""
    first = raw_bars[0]
    dates = tuple(bar.trading_date for bar in raw_bars)
    if any(bar.price_basis is not PriceBasis.RAW for bar in raw_bars):
        raise CanonicalizationError("qfq derivation requires raw bars only")
    if any(bar.symbol != first.symbol or bar.exchange is not first.exchange for bar in raw_bars):
        raise CanonicalizationError("raw series mixes instruments")
    if len(dates) != len(set(dates)) or dates != tuple(sorted(dates)):
        raise CanonicalizationError("raw bars must have unique ascending trading dates")
    if first.symbol != ledger.instrument.symbol or first.exchange is not ledger.instrument.exchange:
        raise CanonicalizationError("corporate-action ledger instrument does not match raw bars")


def _events_by_application_date(
    bars: list[DailyBar],
    ledger: CorporateActionLedger,
) -> dict[date, CorporateActionEvent]:
    """Apply an action after the first tradable session on or after its effective date."""
    applications: dict[date, CorporateActionEvent] = {}
    for event in ledger.events:
        apply_date = next(
            (bar.trading_date for bar in bars if bar.trading_date >= event.effective_date),
            None,
        )
        if apply_date is None:
            raise CanonicalizationError("corporate action has no following raw session")
        if apply_date in applications:
            raise CanonicalizationError("multiple corporate actions apply before one raw session")
        applications[apply_date] = event
    return applications


def _persist_one_canonical_basis(
    provider_manifest: ProviderSeriesManifest,
    bars: list[DailyBar],
    price_basis: PriceBasis,
    data_root: Path,
    *,
    corporate_action_ledger_id: str | None,
    adjustment_factors: tuple[AdjustmentFactor, ...],
) -> CanonicalDatasetManifest:
    """Write a canonical basis and manifest without changing provider-native artifacts."""
    context_sha256 = _sha256(
        _canonical_json(
            {
                "source_manifest_id": provider_manifest.manifest_id,
                "price_basis": price_basis.value,
                "algorithm_version": CANONICAL_ALGORITHM_VERSION,
                "corporate_action_ledger_id": corporate_action_ledger_id,
                "adjustment_factors": [
                    {"date": item.trading_date.isoformat(), "factor": str(item.factor)}
                    for item in adjustment_factors
                ],
            }
        )
    )
    output_bytes = _canonical_parquet_bytes(bars, context_sha256)
    output_sha256 = _sha256(output_bytes)
    output_relative = (
        Path("canonical")
        / "etf_daily"
        / provider_manifest.instrument.exchange.value.lower()
        / provider_manifest.instrument.symbol
        / price_basis.value
        / f"{output_sha256}.parquet"
    )
    output_path = data_root / output_relative
    write_immutable(output_path, output_bytes)
    output_file = ManifestFile(
        relative_path=output_relative.as_posix(),
        sha256=output_sha256,
        size_bytes=len(output_bytes),
    )
    manifest_id = _sha256(
        _canonical_json(
            {
                "instrument": provider_manifest.instrument.model_dump(mode="json"),
                "price_basis": price_basis.value,
                "source_provider": provider_manifest.provider.value,
                "source_manifest_ids": [provider_manifest.manifest_id],
                "algorithm_version": CANONICAL_ALGORITHM_VERSION,
                "corporate_action_ledger_id": corporate_action_ledger_id,
                "output_file": output_file.model_dump(mode="json"),
            }
        )
    )
    manifest = CanonicalDatasetManifest(
        manifest_id=manifest_id,
        instrument=provider_manifest.instrument,
        price_basis=price_basis,
        source_provider=provider_manifest.provider,
        source_manifest_ids=(provider_manifest.manifest_id,),
        algorithm_version=CANONICAL_ALGORITHM_VERSION,
        corporate_action_ledger_id=corporate_action_ledger_id,
        output_file=output_file,
    )
    manifest_path = data_root / "canonical" / "manifests" / f"{manifest_id}.json"
    write_immutable(manifest_path, manifest.model_dump_json(indent=2).encode("utf-8") + b"\n")
    return manifest


def _canonical_parquet_bytes(bars: list[DailyBar], context_sha256: str) -> bytes:
    """Encode canonical daily bars with a deterministic algorithm-context fingerprint."""
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
            b"quant_stack.canonical_algorithm_version": CANONICAL_ALGORITHM_VERSION.encode("ascii"),
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
    """Serialize canonical provenance deterministically before hashing."""
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode(
        "utf-8"
    )


def _sha256(content: bytes) -> str:
    """Return a lowercase SHA-256 digest."""
    return sha256(content).hexdigest()
