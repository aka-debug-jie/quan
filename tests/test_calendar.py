from datetime import datetime
from pathlib import Path

import pytest

from quant_stack.data.calendar import (
    SHANGHAI,
    CalendarNotFoundError,
    CalendarSourceError,
    ExchangeCalendarStore,
    IncompleteSessionError,
)
from quant_stack.data.models import (
    DocumentedNonTradingEvent,
    ETFUniverseInstrument,
    MissingDateKind,
    OfficialEvidence,
)
from quant_stack.models import Exchange, PriceBasis

FIXTURE_ROOT = Path(__file__).parent / "fixtures" / "calendars"
PROJECT_CALENDARS = Path(__file__).parents[1] / "configs" / "calendars"


def instrument() -> ETFUniverseInstrument:
    return ETFUniverseInstrument(
        symbol="510300",
        exchange=Exchange.SSE,
        effective_from=datetime(2024, 1, 2, tzinfo=SHANGHAI).date(),
    )


def test_local_calendar_finds_sessions_across_year_boundary() -> None:
    store = ExchangeCalendarStore(FIXTURE_ROOT)

    assert store.is_session(Exchange.SSE, datetime(2024, 1, 2).date())
    assert (
        store.previous_session(Exchange.SSE, datetime(2025, 1, 2).date())
        == datetime(2024, 12, 31).date()
    )
    assert (
        store.next_session(Exchange.SSE, datetime(2024, 12, 31).date())
        == datetime(2025, 1, 2).date()
    )


def test_calendar_never_infers_missing_years() -> None:
    store = ExchangeCalendarStore(FIXTURE_ROOT)
    with pytest.raises(CalendarNotFoundError, match="missing calendar snapshot"):
        store.is_session(Exchange.SSE, datetime(2026, 1, 2).date())


def test_current_session_is_incomplete_before_close_confirmation() -> None:
    store = ExchangeCalendarStore(FIXTURE_ROOT)
    before_close = datetime(2024, 1, 5, 15, 59, tzinfo=SHANGHAI)
    after_close = datetime(2024, 1, 5, 16, 0, tzinfo=SHANGHAI)

    assert store.latest_completed_session(Exchange.SSE, before_close) == datetime(2024, 1, 4).date()
    assert store.latest_completed_session(Exchange.SSE, after_close) == datetime(2024, 1, 5).date()
    with pytest.raises(IncompleteSessionError, match="exceeds latest completed"):
        store.require_completed_as_of(Exchange.SSE, datetime(2024, 1, 5).date(), before_close)


def test_classifies_non_session_pre_effective_and_missing_dates() -> None:
    store = ExchangeCalendarStore(FIXTURE_ROOT)
    now = datetime(2024, 1, 5, 16, 0, tzinfo=SHANGHAI)

    assert (
        store.classify_date(instrument(), datetime(2024, 1, 1).date(), now=now)
        == MissingDateKind.PRE_EFFECTIVE_RANGE
    )
    assert (
        store.classify_date(instrument(), datetime(2024, 1, 6).date(), now=now)
        == MissingDateKind.NON_SESSION
    )
    assert (
        store.classify_date(instrument(), datetime(2024, 1, 3).date(), now=now)
        == MissingDateKind.EXPECTED_SESSION_MISSING
    )


def test_coverage_report_exposes_expected_session_gaps() -> None:
    store = ExchangeCalendarStore(FIXTURE_ROOT)
    report = store.coverage_report(
        instrument(),
        PriceBasis.RAW,
        {datetime(2024, 1, 2).date(), datetime(2024, 1, 4).date()},
        datetime(2024, 1, 2).date(),
        datetime(2024, 1, 4).date(),
        now=datetime(2024, 1, 5, 16, 0, tzinfo=SHANGHAI),
    )

    assert not report.is_complete
    assert [(record.trading_date, record.kind) for record in report.missing] == [
        (datetime(2024, 1, 3).date(), MissingDateKind.EXPECTED_SESSION_MISSING)
    ]


def test_project_calendar_bundle_materializes_official_closure_dates() -> None:
    store = ExchangeCalendarStore(PROJECT_CALENDARS)

    assert len(store.load_year(Exchange.SSE, 2024).sessions) == 242
    assert len(store.load_year(Exchange.SZSE, 2024).sessions) == 242
    assert not store.is_session(Exchange.SSE, datetime(2024, 10, 1).date())
    assert store.is_session(Exchange.SZSE, datetime(2024, 10, 8).date())


def test_coverage_records_documented_non_trading_session_separately() -> None:
    store = ExchangeCalendarStore(FIXTURE_ROOT)
    evidence = OfficialEvidence(
        url="https://example.invalid/evidence.pdf",
        sha256="e" * 64,
        published_on=datetime(2024, 1, 3).date(),
    )
    event = DocumentedNonTradingEvent(
        dates=(datetime(2024, 1, 3).date(),),
        reason="share conversion suspension",
        evidence=evidence,
    )
    report = store.coverage_report(
        instrument(),
        PriceBasis.RAW,
        {datetime(2024, 1, 2).date(), datetime(2024, 1, 4).date()},
        datetime(2024, 1, 2).date(),
        datetime(2024, 1, 4).date(),
        documented_non_trading_events=(event,),
        now=datetime(2024, 1, 5, 16, 0, tzinfo=SHANGHAI),
    )

    assert report.is_complete
    assert not report.missing
    assert report.documented_non_trading[0].trading_date == datetime(2024, 1, 3).date()


def test_coverage_rejects_evidence_that_conflicts_with_provider_bar() -> None:
    store = ExchangeCalendarStore(FIXTURE_ROOT)
    event = DocumentedNonTradingEvent(
        dates=(datetime(2024, 1, 3).date(),),
        reason="share conversion suspension",
        evidence=OfficialEvidence(
            url="https://example.invalid/evidence.pdf",
            sha256="f" * 64,
            published_on=datetime(2024, 1, 3).date(),
        ),
    )

    with pytest.raises(ValueError, match="has a provider bar"):
        store.coverage_report(
            instrument(),
            PriceBasis.RAW,
            {datetime(2024, 1, 2).date(), datetime(2024, 1, 3).date()},
            datetime(2024, 1, 2).date(),
            datetime(2024, 1, 4).date(),
            documented_non_trading_events=(event,),
            now=datetime(2024, 1, 5, 16, 0, tzinfo=SHANGHAI),
        )


def test_source_archives_are_hash_checked_before_use(tmp_path: Path) -> None:
    store = ExchangeCalendarStore(FIXTURE_ROOT)
    start = datetime(2024, 1, 2).date()
    end = datetime(2024, 1, 4).date()

    with pytest.raises(CalendarSourceError, match="missing local calendar source archive"):
        store.require_source_archives(Exchange.SSE, start, end, tmp_path)

    paths = store.capture_source_archives(
        Exchange.SSE,
        start,
        end,
        tmp_path,
        fetcher=lambda _: b"",
    )

    assert len(paths) == 1
    store.require_source_archives(Exchange.SSE, start, end, tmp_path)
    assert (
        store.capture_source_archives(
            Exchange.SSE,
            start,
            end,
            tmp_path,
            fetcher=lambda _: (_ for _ in ()).throw(AssertionError("must not refetch")),
        )
        == paths
    )
