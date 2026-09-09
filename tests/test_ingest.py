from datetime import UTC, date, datetime
from hashlib import sha256
from pathlib import Path

import pandas as pd
import pytest

from quant_stack.data.akshare_etf import AKShareETFAdapter
from quant_stack.data.calendar import SHANGHAI, CalendarSourceError, ExchangeCalendarStore
from quant_stack.data.evidence import capture_non_trading_evidence
from quant_stack.data.ingest import (
    CoverageError,
    ProvenanceError,
    ingest_universe,
    persist_provider_export,
    split_request_range_by_calendar_year,
    verify_normalized_parquet,
)
from quant_stack.data.models import (
    DocumentedNonTradingEvent,
    ETFHistoryRequest,
    ETFUniverse,
    ETFUniverseInstrument,
    OfficialEvidence,
)
from quant_stack.models import Exchange, PriceBasis

FIXTURES = Path(__file__).parent / "fixtures"
CALENDARS = FIXTURES / "calendars"
AKSHARE = FIXTURES / "akshare"
NOW = datetime(2024, 1, 5, 16, 0, tzinfo=SHANGHAI)


def instrument() -> ETFUniverseInstrument:
    return ETFUniverseInstrument(
        symbol="510300",
        exchange=Exchange.SSE,
        effective_from=date(2024, 1, 2),
    )


def request(price_basis: PriceBasis = PriceBasis.RAW) -> ETFHistoryRequest:
    return ETFHistoryRequest(
        instrument=instrument(),
        start_date=date(2024, 1, 2),
        as_of_date=date(2024, 1, 4),
        price_basis=price_basis,
    )


def raw_frame() -> pd.DataFrame:
    return pd.read_csv(AKSHARE / "etf_daily_raw.csv")


def qfq_frame() -> pd.DataFrame:
    return pd.read_csv(AKSHARE / "etf_daily_qfq.csv")


def seed_calendar_source_archive(data_root: Path, calendar: ExchangeCalendarStore) -> None:
    calendar.capture_source_archives(
        Exchange.SSE,
        date(2024, 1, 2),
        date(2024, 1, 4),
        data_root,
        fetcher=lambda _: b"",
    )


def documented_event() -> DocumentedNonTradingEvent:
    return DocumentedNonTradingEvent(
        dates=(date(2024, 1, 3),),
        reason="share conversion suspension",
        evidence=OfficialEvidence(
            url="https://example.invalid/evidence.pdf",
            sha256=sha256(b"official-evidence").hexdigest(),
            published_on=date(2024, 1, 3),
        ),
    )


def test_persists_raw_parquet_and_bidirectional_manifest(tmp_path: Path) -> None:
    result = persist_provider_export(
        request(),
        raw_frame(),
        tmp_path,
        ExchangeCalendarStore(CALENDARS),
        captured_at=datetime(2024, 1, 5, tzinfo=UTC),
        now=NOW,
    )

    assert result.raw_path.is_file()
    assert result.normalized_path.is_file()
    assert result.manifest_path.is_file()
    assert result.manifest.coverage_complete
    assert verify_normalized_parquet(result.normalized_path, tmp_path) == result.manifest


def test_identical_ingestion_reuses_immutable_manifest(tmp_path: Path) -> None:
    calendar = ExchangeCalendarStore(CALENDARS)
    first = persist_provider_export(
        request(),
        raw_frame(),
        tmp_path,
        calendar,
        captured_at=datetime(2024, 1, 5, tzinfo=UTC),
        now=NOW,
    )
    retry = persist_provider_export(
        request(),
        raw_frame(),
        tmp_path,
        calendar,
        captured_at=datetime(2024, 2, 5, tzinfo=UTC),
        now=NOW,
    )

    assert retry.manifest == first.manifest
    assert retry.manifest.first_captured_at == first.manifest.first_captured_at


def test_partial_provider_export_is_persisted_but_not_marked_complete(tmp_path: Path) -> None:
    partial = raw_frame().drop(index=1)
    result = persist_provider_export(
        request(),
        partial,
        tmp_path,
        ExchangeCalendarStore(CALENDARS),
        now=NOW,
    )

    assert not result.manifest.coverage_complete
    assert result.raw_path.is_file()
    assert result.manifest_path.is_file()


def test_verification_rejects_tampered_normalized_file(tmp_path: Path) -> None:
    result = persist_provider_export(
        request(), raw_frame(), tmp_path, ExchangeCalendarStore(CALENDARS), now=NOW
    )
    result.normalized_path.write_bytes(b"tampered")

    with pytest.raises(ValueError, match="expected exactly one manifest"):
        verify_normalized_parquet(result.normalized_path, tmp_path)


def test_incremental_ingestion_refuses_tampered_existing_parquet(tmp_path: Path) -> None:
    result = persist_provider_export(
        request(), raw_frame(), tmp_path, ExchangeCalendarStore(CALENDARS), now=NOW
    )
    result.normalized_path.write_bytes(b"tampered")
    universe = ETFUniverse(universe_id="test", version=1, instruments=(instrument(),))
    calendar = ExchangeCalendarStore(CALENDARS)
    seed_calendar_source_archive(tmp_path, calendar)

    with pytest.raises(ProvenanceError):
        ingest_universe(
            universe,
            date(2024, 1, 2),
            date(2024, 1, 4),
            tmp_path,
            calendar,
            AKShareETFAdapter(lambda _: raw_frame(), sleep_fn=lambda _: None),
            now=NOW,
        )


def test_universe_backfill_only_fetches_missing_sessions_then_becomes_idempotent(
    tmp_path: Path,
) -> None:
    calls: list[ETFHistoryRequest] = []

    def fetcher(history_request: ETFHistoryRequest) -> pd.DataFrame:
        calls.append(history_request)
        if history_request.price_basis is PriceBasis.RAW:
            return raw_frame()
        return qfq_frame()

    universe = ETFUniverse(universe_id="test", version=1, instruments=(instrument(),))
    calendar = ExchangeCalendarStore(CALENDARS)
    seed_calendar_source_archive(tmp_path, calendar)
    first = ingest_universe(
        universe,
        date(2024, 1, 2),
        date(2024, 1, 4),
        tmp_path,
        calendar,
        AKShareETFAdapter(fetcher, sleep_fn=lambda _: None),
        now=NOW,
    )
    second = ingest_universe(
        universe,
        date(2024, 1, 2),
        date(2024, 1, 4),
        tmp_path,
        calendar,
        AKShareETFAdapter(fetcher, sleep_fn=lambda _: None),
        now=NOW,
    )

    assert len(first.ingestions) == 2
    assert len(calls) == 2
    assert not second.ingestions
    assert all(report.is_complete for report in second.coverage_reports)


def test_incremental_ingestion_requests_only_the_missing_session_range(tmp_path: Path) -> None:
    calendar = ExchangeCalendarStore(CALENDARS)
    partial_raw = raw_frame().drop(index=1)
    partial_qfq = qfq_frame().drop(index=1)
    persist_provider_export(request(PriceBasis.RAW), partial_raw, tmp_path, calendar, now=NOW)
    persist_provider_export(request(PriceBasis.QFQ), partial_qfq, tmp_path, calendar, now=NOW)
    seed_calendar_source_archive(tmp_path, calendar)
    calls: list[ETFHistoryRequest] = []

    def fetcher(history_request: ETFHistoryRequest) -> pd.DataFrame:
        calls.append(history_request)
        source = raw_frame() if history_request.price_basis is PriceBasis.RAW else qfq_frame()
        return source[source["日期"].eq("2024-01-03")]

    result = ingest_universe(
        ETFUniverse(universe_id="test", version=1, instruments=(instrument(),)),
        date(2024, 1, 2),
        date(2024, 1, 4),
        tmp_path,
        calendar,
        AKShareETFAdapter(fetcher, sleep_fn=lambda _: None),
        now=NOW,
    )

    assert [(item.start_date, item.as_of_date) for item in calls] == [
        (date(2024, 1, 3), date(2024, 1, 3)),
        (date(2024, 1, 3), date(2024, 1, 3)),
    ]
    assert all(report.is_complete for report in result.coverage_reports)


def test_long_request_is_split_on_local_calendar_year_boundaries() -> None:
    chunks = split_request_range_by_calendar_year(
        ExchangeCalendarStore(CALENDARS),
        "SSE",
        date(2024, 1, 2),
        date(2025, 1, 3),
    )

    assert chunks == (
        (date(2024, 1, 2), date(2024, 12, 31)),
        (date(2025, 1, 2), date(2025, 1, 3)),
    )


def test_v2_reattests_retained_export_with_documented_non_trading_evidence(
    tmp_path: Path,
) -> None:
    calendar = ExchangeCalendarStore(CALENDARS)
    partial_raw = raw_frame().drop(index=1)
    partial_qfq = qfq_frame().drop(index=1)
    old_raw = persist_provider_export(
        request(PriceBasis.RAW),
        partial_raw,
        tmp_path,
        calendar,
        now=NOW,
    )
    old_qfq = persist_provider_export(
        request(PriceBasis.QFQ),
        partial_qfq,
        tmp_path,
        calendar,
        now=NOW,
    )
    event = documented_event()
    capture_non_trading_evidence(
        (event,),
        tmp_path,
        fetcher=lambda _: b"official-evidence",
    )
    seed_calendar_source_archive(tmp_path, calendar)
    v2_instrument = ETFUniverseInstrument(
        symbol="510300",
        exchange=Exchange.SSE,
        effective_from=date(2024, 1, 2),
        documented_non_trading_events=(event,),
    )
    v2_universe = ETFUniverse(universe_id="v2", version=2, instruments=(v2_instrument,))

    result = ingest_universe(
        v2_universe,
        date(2024, 1, 2),
        date(2024, 1, 4),
        tmp_path,
        calendar,
        AKShareETFAdapter(
            lambda _: (_ for _ in ()).throw(AssertionError("must not refetch documented absence")),
            sleep_fn=lambda _: None,
        ),
        now=NOW,
    )

    assert len(result.ingestions) == 2
    assert all(item.manifest.coverage_complete for item in result.ingestions)
    assert all(item.manifest.coverage_documented_non_trading for item in result.ingestions)
    assert all(item.manifest.request.universe_id == "v2" for item in result.ingestions)
    assert {item.normalized_path for item in result.ingestions}.isdisjoint(
        {old_raw.normalized_path, old_qfq.normalized_path}
    )
    assert all(report.is_complete for report in result.coverage_reports)
    for item in result.ingestions:
        assert verify_normalized_parquet(item.normalized_path, tmp_path) == item.manifest


def test_universe_ingestion_requires_local_calendar_source_archives(tmp_path: Path) -> None:
    universe = ETFUniverse(universe_id="test", version=1, instruments=(instrument(),))

    with pytest.raises(CalendarSourceError, match="missing local calendar source archive"):
        ingest_universe(
            universe,
            date(2024, 1, 2),
            date(2024, 1, 4),
            tmp_path,
            ExchangeCalendarStore(CALENDARS),
            AKShareETFAdapter(lambda _: raw_frame(), sleep_fn=lambda _: None),
            now=NOW,
        )


def test_universe_ingestion_fails_when_expected_session_remains_missing(tmp_path: Path) -> None:
    incomplete_adapter = AKShareETFAdapter(
        lambda _: raw_frame().drop(index=1), sleep_fn=lambda _: None
    )
    universe = ETFUniverse(universe_id="test", version=1, instruments=(instrument(),))
    calendar = ExchangeCalendarStore(CALENDARS)
    seed_calendar_source_archive(tmp_path, calendar)

    with pytest.raises(CoverageError, match="expected session data is missing"):
        ingest_universe(
            universe,
            date(2024, 1, 2),
            date(2024, 1, 4),
            tmp_path,
            calendar,
            incomplete_adapter,
            now=NOW,
        )
