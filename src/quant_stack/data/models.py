"""Data-foundation models independent of strategy and backtest code."""

from __future__ import annotations

from datetime import date, datetime, timedelta
from decimal import Decimal
from enum import StrEnum
from itertools import pairwise
from typing import Annotated, Literal

from pydantic import Field, field_validator, model_validator

from quant_stack.models import DomainModel, Exchange, Instrument, ManifestFile, PriceBasis

LEGACY_CONTEXT_SHA256 = "0" * 64


class OfficialEvidence(DomainModel):
    """A content-addressed primary source supporting an explicit market-data exception."""

    url: Annotated[str, Field(min_length=1)]
    sha256: Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]
    published_on: date


class DocumentedNonTradingEvent(DomainModel):
    """A verified asset-level event for sessions that intentionally have no market bar."""

    dates: tuple[date, ...]
    reason: Annotated[str, Field(min_length=1)]
    evidence: OfficialEvidence

    @model_validator(mode="after")
    def validate_dates(self) -> DocumentedNonTradingEvent:
        """Require a non-empty, ordered, non-duplicated set of declared dates."""
        if not self.dates:
            raise ValueError("documented non-trading event must contain at least one date")
        if tuple(sorted(set(self.dates))) != self.dates:
            raise ValueError("documented non-trading event dates must be unique and sorted")
        return self


class ETFUniverseInstrument(Instrument):
    """An ETF with an explicit interval in which it belongs to a universe version."""

    effective_from: date
    effective_to: date | None = None
    documented_non_trading_events: tuple[DocumentedNonTradingEvent, ...] = ()

    @model_validator(mode="after")
    def validate_effective_interval(self) -> ETFUniverseInstrument:
        """Reject a universe interval that ends before it begins."""
        if self.effective_to is not None and self.effective_to < self.effective_from:
            raise ValueError("effective_to must not be earlier than effective_from")
        if self.exchange is Exchange.TEST:
            raise ValueError("ETF universe instruments must use SSE or SZSE")
        declared_dates: set[date] = set()
        for event in self.documented_non_trading_events:
            for event_date in event.dates:
                if event_date < self.effective_from or (
                    self.effective_to is not None and event_date > self.effective_to
                ):
                    raise ValueError("documented non-trading date is outside effective interval")
                if event_date in declared_dates:
                    raise ValueError("documented non-trading dates must not overlap")
                declared_dates.add(event_date)
        return self


class ETFUniverse(DomainModel):
    """Versioned point-in-time ETF universe used only by the ingestion layer."""

    universe_id: Annotated[str, Field(min_length=1)]
    version: Annotated[int, Field(ge=1)]
    instruments: tuple[ETFUniverseInstrument, ...]

    @model_validator(mode="after")
    def validate_unique_instruments(self) -> ETFUniverse:
        """Reject overlapping effective intervals for one exchange and symbol."""
        grouped: dict[tuple[Exchange, str], list[ETFUniverseInstrument]] = {}
        for instrument in self.instruments:
            grouped.setdefault((instrument.exchange, instrument.symbol), []).append(instrument)
        for key, entries in grouped.items():
            ordered = sorted(entries, key=lambda item: item.effective_from)
            for previous, current in pairwise(ordered):
                if previous.effective_to is None or current.effective_from <= previous.effective_to:
                    raise ValueError(f"overlapping effective intervals for {key[0]}:{key[1]}")
        return self


class ETFHistoryRequest(DomainModel):
    """A bounded daily ETF request to the AKShare provider adapter."""

    instrument: ETFUniverseInstrument
    universe_id: Annotated[str, Field(min_length=1)] = "ad_hoc"
    universe_version: Annotated[int, Field(ge=1)] = 1
    start_date: date
    as_of_date: date
    price_basis: PriceBasis
    period: Literal["daily"] = "daily"

    @model_validator(mode="after")
    def validate_date_range(self) -> ETFHistoryRequest:
        """Require a bounded interval inside the instrument's effective range."""
        if self.start_date > self.as_of_date:
            raise ValueError("start_date must not be later than as_of_date")
        if self.start_date < self.instrument.effective_from:
            raise ValueError("start_date must not precede instrument effective_from")
        if (
            self.instrument.effective_to is not None
            and self.as_of_date > self.instrument.effective_to
        ):
            raise ValueError("as_of_date must not exceed instrument effective_to")
        return self


class IngestionManifest(DomainModel):
    """Immutable provenance linking one normalized Parquet dataset to its source export."""

    manifest_id: Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]
    provider: Literal["akshare"]
    adapter_version: Annotated[str, Field(min_length=1)]
    request: ETFHistoryRequest
    first_captured_at: datetime
    raw_file: ManifestFile
    normalized_file: ManifestFile
    row_count: Annotated[int, Field(gt=0)]
    first_trading_date: date
    last_trading_date: date
    calendar_sha256: Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]
    context_sha256: Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")] = LEGACY_CONTEXT_SHA256
    coverage_complete: bool
    coverage_missing: tuple[MissingDateRecord, ...] = ()
    coverage_documented_non_trading: tuple[DocumentedNonTradingRecord, ...] = ()

    @field_validator("first_captured_at")
    @classmethod
    def require_timezone(cls, value: datetime) -> datetime:
        """Reject ambiguous provenance timestamps."""
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("first_captured_at must be timezone-aware")
        return value

    @model_validator(mode="after")
    def validate_dates(self) -> IngestionManifest:
        """Keep recorded coverage consistent with the originating request."""
        if self.first_trading_date > self.last_trading_date:
            raise ValueError("first_trading_date must not follow last_trading_date")
        if self.first_trading_date < self.request.start_date:
            raise ValueError("normalized data starts before requested range")
        if self.last_trading_date > self.request.as_of_date:
            raise ValueError("normalized data ends after requested range")
        if self.coverage_complete and any(
            record.kind == MissingDateKind.EXPECTED_SESSION_MISSING
            for record in self.coverage_missing
        ):
            raise ValueError("complete coverage cannot contain expected-session gaps")
        return self


class ProviderId(StrEnum):
    """Provider identities kept separate until a canonicalization decision is audited."""

    AKSHARE_EASTMONEY = "akshare_eastmoney"
    SZSE_OFFICIAL = "szse_official"
    SINA = "sina"
    TUSHARE = "tushare"


class ProviderSeriesManifest(DomainModel):
    """Provenance for one provider-native daily-bar series independent of canonical data."""

    manifest_id: Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]
    provider: ProviderId
    instrument: Instrument
    price_basis: PriceBasis
    volume_unit: Literal["shares", "lots", "unspecified"] = "unspecified"
    source_url: Annotated[str, Field(min_length=1)]
    retrieved_at: datetime
    request_parameters: dict[str, str]
    http_metadata: dict[str, str]
    parser_version: Annotated[str, Field(min_length=1)]
    normalization_version: Annotated[str, Field(min_length=1)]
    raw_file: ManifestFile
    normalized_file: ManifestFile
    row_count: Annotated[int, Field(gt=0)]
    first_trading_date: date
    last_trading_date: date

    @field_validator("retrieved_at")
    @classmethod
    def require_retrieval_timezone(cls, value: datetime) -> datetime:
        """Require an unambiguous provider retrieval timestamp."""
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("retrieved_at must be timezone-aware")
        return value

    @model_validator(mode="after")
    def validate_provider_series_dates(self) -> ProviderSeriesManifest:
        """Keep provider-native coverage bounds internally consistent."""
        if self.first_trading_date > self.last_trading_date:
            raise ValueError("first_trading_date must not follow last_trading_date")
        return self


class CorporateActionKind(StrEnum):
    """Official events that change raw-price continuity without filling trade bars."""

    CASH_DISTRIBUTION = "cash_distribution"
    SHARE_SPLIT = "share_split"


class CorporateActionEvent(DomainModel):
    """One evidence-backed corporate action used by deterministic price adjustment."""

    effective_date: date
    kind: CorporateActionKind
    cash_per_unit: Decimal | None = None
    split_ratio: Decimal | None = None
    evidence: OfficialEvidence
    availability_evidence: OfficialEvidence | None = None
    value_evidence: OfficialEvidence | None = None
    event_announcement_date: date | None = None
    record_date: date | None = None
    payment_date: date | None = None
    evidence_type: (
        Literal["original_notice", "annual_report", "legally_published_original"] | None
    ) = None
    retrospective_verification: bool = False
    verification_status: Literal["candidate", "official_evidence_chain_verified"] = "candidate"

    @model_validator(mode="after")
    def validate_action_payload(self) -> CorporateActionEvent:
        """Require exactly the action parameter relevant to the declared event kind."""
        if self.kind is CorporateActionKind.CASH_DISTRIBUTION:
            if (
                self.cash_per_unit is None
                or self.cash_per_unit <= 0
                or self.split_ratio is not None
            ):
                raise ValueError("cash distribution requires positive cash_per_unit only")
        if self.kind is CorporateActionKind.SHARE_SPLIT:
            if self.split_ratio is None or self.split_ratio <= 0 or self.cash_per_unit is not None:
                raise ValueError("share split requires positive split_ratio only")
        if self.verification_status == "official_evidence_chain_verified" and (
            self.availability_evidence is None or self.value_evidence is None
        ):
            raise ValueError("verified action requires availability and value evidence")
        if self.record_date is not None and self.record_date > self.effective_date:
            raise ValueError("record_date must not follow effective_date")
        if self.payment_date is not None and self.payment_date < self.effective_date:
            raise ValueError("payment_date must not precede effective_date")
        return self


class CorporateActionLedger(DomainModel):
    """Versioned official action ledger; incomplete ledgers may not produce canonical qfq data."""

    ledger_id: Annotated[str, Field(min_length=1)]
    version: Annotated[int, Field(ge=1)]
    instrument: Instrument
    completeness: Literal["incomplete", "complete"]
    events: tuple[CorporateActionEvent, ...] = ()

    @model_validator(mode="after")
    def validate_event_order(self) -> CorporateActionLedger:
        """Reject duplicate corporate-action effective dates in one ledger version."""
        dates = tuple(event.effective_date for event in self.events)
        if len(dates) != len(set(dates)):
            raise ValueError("corporate-action ledger dates must be unique")
        if dates != tuple(sorted(dates)):
            raise ValueError("corporate-action ledger events must be sorted")
        return self


class CanonicalDatasetManifest(DomainModel):
    """Provenance for a dataset selected or derived by the canonicalization layer."""

    manifest_id: Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]
    instrument: Instrument
    price_basis: PriceBasis
    source_provider: ProviderId
    source_manifest_ids: tuple[Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")], ...]
    algorithm_version: Annotated[str, Field(min_length=1)]
    corporate_action_ledger_id: Annotated[str, Field(min_length=1)] | None = None
    output_file: ManifestFile


class CalendarSource(OfficialEvidence):
    """A content-addressed official notice used to build an annual calendar."""


class ExchangeCalendarYear(DomainModel):
    """Explicit local sessions for one exchange and calendar year."""

    exchange: Exchange
    year: Annotated[int, Field(ge=1990, le=2100)]
    sources: tuple[CalendarSource, ...]
    sessions: tuple[date, ...] = ()
    closed_dates: tuple[date, ...] = ()

    @model_validator(mode="before")
    @classmethod
    def materialize_weekday_sessions(cls, value: object) -> object:
        """Expand explicit official closure dates into local weekday sessions when needed."""
        if not isinstance(value, dict) or value.get("sessions"):
            return value
        year = value.get("year")
        closed_dates = value.get("closed_dates")
        if not isinstance(year, int) or not isinstance(closed_dates, list):
            return value
        parsed_closed_dates = {
            item if isinstance(item, date) else date.fromisoformat(str(item))
            for item in closed_dates
        }
        current = date(year, 1, 1)
        final = date(year, 12, 31)
        sessions: list[date] = []
        while current <= final:
            if current.weekday() < 5 and current not in parsed_closed_dates:
                sessions.append(current)
            current += timedelta(days=1)
        materialized = dict(value)
        materialized["sessions"] = sessions
        return materialized

    @model_validator(mode="after")
    def validate_sessions(self) -> ExchangeCalendarYear:
        """Require an authoritative source and ordered weekday-only sessions."""
        if self.exchange is Exchange.TEST:
            raise ValueError("exchange calendars must use SSE or SZSE")
        if not self.sources:
            raise ValueError("calendar must record at least one official source")
        if not self.sessions:
            raise ValueError("calendar must contain at least one session")
        if tuple(sorted(set(self.sessions))) != self.sessions:
            raise ValueError("calendar sessions must be unique and sorted")
        if any(session.year != self.year or session.weekday() > 4 for session in self.sessions):
            raise ValueError("calendar sessions must be weekdays in the declared year")
        if any(closed.year != self.year for closed in self.closed_dates):
            raise ValueError("calendar closure dates must be in the declared year")
        if any(closed in self.sessions for closed in self.closed_dates):
            raise ValueError("calendar closure dates must not appear in sessions")
        return self


class MissingDateKind(StrEnum):
    """Stable labels for a date's validity status in a requested coverage interval."""

    NON_SESSION = "non_session"
    PRE_EFFECTIVE_RANGE = "pre_effective_range"
    INCOMPLETE_CURRENT_SESSION = "incomplete_current_session"
    EXPECTED_SESSION_MISSING = "expected_session_missing"


class MissingDateRecord(DomainModel):
    """One classified date observed during historical coverage validation."""

    trading_date: date
    kind: MissingDateKind


class DocumentedNonTradingRecord(DomainModel):
    """One evidence-backed scheduled session intentionally absent from a bar series."""

    trading_date: date
    reason: Annotated[str, Field(min_length=1)]
    evidence: OfficialEvidence


class CoverageReport(DomainModel):
    """Calendar-aware coverage result for one ETF and one price-basis dataset."""

    instrument: ETFUniverseInstrument
    price_basis: PriceBasis
    start_date: date
    as_of_date: date
    present_dates: tuple[date, ...]
    missing: tuple[MissingDateRecord, ...]
    documented_non_trading: tuple[DocumentedNonTradingRecord, ...] = ()

    @property
    def is_complete(self) -> bool:
        """Return whether every expected completed session is represented."""
        return not any(record.kind == "expected_session_missing" for record in self.missing)
