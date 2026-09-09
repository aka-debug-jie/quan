"""Offline, source-attributed Shanghai and Shenzhen trading calendars."""

from __future__ import annotations

import json
from collections.abc import Callable
from datetime import date, datetime, time
from hashlib import sha256
from pathlib import Path
from urllib.request import Request, urlopen
from zoneinfo import ZoneInfo

import yaml

from quant_stack.data.models import (
    CalendarSource,
    CoverageReport,
    DocumentedNonTradingEvent,
    DocumentedNonTradingRecord,
    ETFUniverseInstrument,
    ExchangeCalendarYear,
    MissingDateKind,
    MissingDateRecord,
)
from quant_stack.models import Exchange, PriceBasis
from quant_stack.snapshot import write_immutable

SHANGHAI = ZoneInfo("Asia/Shanghai")
MARKET_CLOSE_CONFIRMATION = time(16, 0)


class CalendarNotFoundError(ValueError):
    """Raised when a required local annual calendar snapshot is unavailable."""


class IncompleteSessionError(ValueError):
    """Raised when ingestion targets a session that is not yet confirmed closed."""


class CalendarSourceError(ValueError):
    """Raised when an official calendar source cannot be captured or verified locally."""


SourceFetcher = Callable[[str], bytes]


class ExchangeCalendarStore:
    """Read-only access to source-attributed, annual local calendar snapshots."""

    def __init__(self, root: Path) -> None:
        self._root = root
        self._cache: dict[tuple[Exchange, int], ExchangeCalendarYear] = {}

    def load_year(self, exchange: Exchange, year: int) -> ExchangeCalendarYear:
        """Load one exchange-year snapshot or fail rather than infer sessions."""
        key = (exchange, year)
        if key not in self._cache:
            path = self._root / exchange.value.lower() / f"{year}.yaml"
            if path.is_file():
                loaded = yaml.safe_load(path.read_text(encoding="utf-8"))
            else:
                bundle_path = self._root / f"{exchange.value.lower()}.yaml"
                if not bundle_path.is_file():
                    raise CalendarNotFoundError(f"missing calendar snapshot: {path}")
                bundle = yaml.safe_load(bundle_path.read_text(encoding="utf-8"))
                loaded = _calendar_from_bundle(bundle, exchange, year, bundle_path)
            calendar = ExchangeCalendarYear.model_validate(loaded)
            if calendar.exchange is not exchange or calendar.year != year:
                raise CalendarNotFoundError(f"calendar identity does not match path: {path}")
            self._cache[key] = calendar
        return self._cache[key]

    def is_session(self, exchange: Exchange, value: date) -> bool:
        """Return whether a date is explicitly listed as a session locally."""
        return value in self.load_year(exchange, value.year).sessions

    def sessions_between(self, exchange: Exchange, start: date, end: date) -> tuple[date, ...]:
        """Return explicit sessions across inclusive bounds without provider inference."""
        if start > end:
            return ()
        sessions: list[date] = []
        for year in range(start.year, end.year + 1):
            calendar = self.load_year(exchange, year)
            sessions.extend(session for session in calendar.sessions if start <= session <= end)
        return tuple(sessions)

    def fingerprint(self, exchange: Exchange, start: date, end: date) -> str:
        """Hash the exact local calendar snapshots used for an interval."""
        snapshots = [
            self.load_year(exchange, year).model_dump(mode="json")
            for year in range(start.year, end.year + 1)
        ]
        serialized = json.dumps(
            snapshots,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        return sha256(serialized.encode("utf-8")).hexdigest()

    def require_source_archives(
        self,
        exchange: Exchange,
        start: date,
        end: date,
        data_root: Path,
    ) -> None:
        """Require every configured source body to exist locally with its declared hash."""
        for source in self._sources_between(exchange, start, end):
            archive_path = _source_archive_path(data_root, source.sha256)
            if not archive_path.is_file():
                raise CalendarSourceError(f"missing local calendar source archive: {archive_path}")
            if _sha256(archive_path.read_bytes()) != source.sha256:
                raise CalendarSourceError(f"calendar source archive hash mismatch: {archive_path}")

    def capture_source_archives(
        self,
        exchange: Exchange,
        start: date,
        end: date,
        data_root: Path,
        fetcher: SourceFetcher | None = None,
    ) -> tuple[Path, ...]:
        """Fetch, hash-check, and immutably archive configured official notices for an interval."""
        fetch = fetcher or _fetch_source_bytes
        archived: list[Path] = []
        for source in self._sources_between(exchange, start, end):
            archive_path = _source_archive_path(data_root, source.sha256)
            if archive_path.is_file():
                if _sha256(archive_path.read_bytes()) != source.sha256:
                    raise CalendarSourceError(
                        f"calendar source archive hash mismatch: {archive_path}"
                    )
            else:
                content = fetch(source.url)
                if _sha256(content) != source.sha256:
                    raise CalendarSourceError(
                        f"calendar source content does not match configured hash: {source.url}"
                    )
                write_immutable(archive_path, content)
            archived.append(archive_path)
        return tuple(archived)

    def previous_session(self, exchange: Exchange, value: date) -> date:
        """Return the session immediately preceding a date, including across years."""
        cursor_year = value.year
        while cursor_year >= 1990:
            sessions = self.load_year(exchange, cursor_year).sessions
            candidates = [session for session in sessions if session < value]
            if candidates:
                return candidates[-1]
            cursor_year -= 1
            value = date(cursor_year + 1, 1, 1)
        raise CalendarNotFoundError("no prior local calendar session found")

    def next_session(self, exchange: Exchange, value: date) -> date:
        """Return the session immediately following a date, including across years."""
        cursor_year = value.year
        while cursor_year <= 2100:
            sessions = self.load_year(exchange, cursor_year).sessions
            candidates = [session for session in sessions if session > value]
            if candidates:
                return candidates[0]
            cursor_year += 1
            value = date(cursor_year - 1, 12, 31)
        raise CalendarNotFoundError("no later local calendar session found")

    def latest_completed_session(
        self,
        exchange: Exchange,
        now: datetime | None = None,
    ) -> date:
        """Return the latest session eligible for ingestion under the 16:00 CST cutoff."""
        local_now = (now or datetime.now(SHANGHAI)).astimezone(SHANGHAI)
        today = local_now.date()
        if (
            self.is_session(exchange, today)
            and local_now.timetz().replace(tzinfo=None) >= MARKET_CLOSE_CONFIRMATION
        ):
            return today
        return self.previous_session(exchange, today)

    def require_completed_as_of(
        self,
        exchange: Exchange,
        as_of_date: date,
        now: datetime | None = None,
    ) -> None:
        """Reject a requested cutoff later than the latest confirmed closed session."""
        latest = self.latest_completed_session(exchange, now)
        if as_of_date > latest:
            raise IncompleteSessionError(
                f"as_of_date {as_of_date.isoformat()} exceeds latest completed session "
                f"{latest.isoformat()}"
            )

    def classify_date(
        self,
        instrument: ETFUniverseInstrument,
        value: date,
        *,
        now: datetime | None = None,
    ) -> MissingDateKind | None:
        """Classify a date without guessing whether an absent bar is a suspension."""
        if value < instrument.effective_from or (
            instrument.effective_to is not None and value > instrument.effective_to
        ):
            return MissingDateKind.PRE_EFFECTIVE_RANGE
        if not self.is_session(instrument.exchange, value):
            return MissingDateKind.NON_SESSION
        if value > self.latest_completed_session(instrument.exchange, now):
            return MissingDateKind.INCOMPLETE_CURRENT_SESSION
        return MissingDateKind.EXPECTED_SESSION_MISSING

    def coverage_report(
        self,
        instrument: ETFUniverseInstrument,
        price_basis: PriceBasis,
        present_dates: set[date],
        start_date: date,
        as_of_date: date,
        *,
        documented_non_trading_events: tuple[DocumentedNonTradingEvent, ...] = (),
        now: datetime | None = None,
    ) -> CoverageReport:
        """Return a report that separates verified non-trading sessions from unexplained gaps."""
        missing: list[MissingDateRecord] = []
        documented_non_trading: list[DocumentedNonTradingRecord] = []
        events_by_date = {
            event_date: event
            for event in documented_non_trading_events
            for event_date in event.dates
        }
        for event_date in events_by_date:
            if not self.is_session(instrument.exchange, event_date):
                raise ValueError(
                    "documented non-trading date is not an exchange session: "
                    f"{event_date.isoformat()}"
                )
            if event_date in present_dates:
                raise ValueError(
                    f"documented non-trading date has a provider bar: {event_date.isoformat()}"
                )
        effective_start = max(start_date, instrument.effective_from)
        if start_date < instrument.effective_from:
            missing.append(
                MissingDateRecord(
                    trading_date=start_date,
                    kind=MissingDateKind.PRE_EFFECTIVE_RANGE,
                )
            )
        latest = self.latest_completed_session(instrument.exchange, now)
        if as_of_date > latest:
            missing.append(
                MissingDateRecord(
                    trading_date=as_of_date,
                    kind=MissingDateKind.INCOMPLETE_CURRENT_SESSION,
                )
            )
        expected_end = min(as_of_date, latest)
        for session in self.sessions_between(instrument.exchange, effective_start, expected_end):
            if session in present_dates:
                continue
            documented_event = events_by_date.get(session)
            if documented_event is not None:
                documented_non_trading.append(
                    DocumentedNonTradingRecord(
                        trading_date=session,
                        reason=documented_event.reason,
                        evidence=documented_event.evidence,
                    )
                )
            else:
                missing.append(
                    MissingDateRecord(
                        trading_date=session,
                        kind=MissingDateKind.EXPECTED_SESSION_MISSING,
                    )
                )
        return CoverageReport(
            instrument=instrument,
            price_basis=price_basis,
            start_date=start_date,
            as_of_date=as_of_date,
            present_dates=tuple(sorted(present_dates)),
            missing=tuple(missing),
            documented_non_trading=tuple(documented_non_trading),
        )

    def _sources_between(
        self,
        exchange: Exchange,
        start: date,
        end: date,
    ) -> tuple[CalendarSource, ...]:
        """Return source records once each, preserving local annual-calendar order."""
        unique: dict[str, CalendarSource] = {}
        for year in range(start.year, end.year + 1):
            for source in self.load_year(exchange, year).sources:
                unique.setdefault(source.sha256, source)
        return tuple(unique.values())


def _calendar_from_bundle(
    bundle: object,
    exchange: Exchange,
    year: int,
    path: Path,
) -> object:
    """Extract one annual snapshot from a compact exchange-level calendar bundle."""
    if not isinstance(bundle, dict):
        raise CalendarNotFoundError(f"calendar bundle is not a mapping: {path}")
    years = bundle.get("years")
    if not isinstance(years, dict) or str(year) not in years:
        raise CalendarNotFoundError(f"missing year {year} in calendar bundle: {path}")
    annual = years[str(year)]
    if not isinstance(annual, dict):
        raise CalendarNotFoundError(f"calendar year is not a mapping: {path}")
    merged = dict(annual)
    merged["exchange"] = exchange.value
    merged["year"] = year
    return merged


def _source_archive_path(data_root: Path, sha256_value: str) -> Path:
    """Return the content-addressed local path for one official calendar notice body."""
    return data_root / "raw" / "calendar_sources" / sha256_value / "notice.html"


def _fetch_source_bytes(url: str) -> bytes:
    """Download one source document with a bounded request timeout."""
    request = Request(url, headers={"User-Agent": "quant-stack-calendar-source/1.0"})
    try:
        with urlopen(request, timeout=30) as response:
            return bytes(response.read())
    except OSError as error:
        raise CalendarSourceError(f"unable to fetch calendar source: {url}") from error


def _sha256(content: bytes) -> str:
    """Return a lowercase SHA-256 digest for locally retained source content."""
    return sha256(content).hexdigest()
