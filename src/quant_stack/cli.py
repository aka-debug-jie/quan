"""Command-line entry points for the M0 research skeleton."""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path
from typing import Annotated

import typer

from quant_stack.data.akshare_etf import AKShareETFAdapter, DataFetchError
from quant_stack.data.calendar import (
    CalendarNotFoundError,
    CalendarSourceError,
    ExchangeCalendarStore,
    IncompleteSessionError,
)
from quant_stack.data.corporate_actions import (
    CorporateActionLedgerError,
    load_corporate_action_ledger,
)
from quant_stack.data.evidence import (
    EvidenceArchiveError,
    archive_corporate_action_source,
    capture_corporate_action_evidence,
    capture_non_trading_evidence,
    require_non_trading_evidence,
)
from quant_stack.data.ingest import (
    CoverageError,
    ProvenanceError,
    ingest_universe,
    load_etf_universe,
    normalized_dates,
    verify_normalized_parquet,
)
from quant_stack.data.models import ETFHistoryRequest, ProviderSeriesManifest
from quant_stack.data.sina_etf import (
    SinaProviderError,
    fetch_sina_adjustment_candidate,
    fetch_sina_etf_history,
    load_sina_provider_bars,
    persist_sina_adjustment_candidate,
    persist_sina_etf_history,
)
from quant_stack.data.szse_official import (
    SZSEProviderError,
    fetch_szse_daily_history,
    load_szse_provider_bars,
    persist_szse_daily_history,
    reattest_szse_daily_history,
)
from quant_stack.data_qualification import persist_qualification_report, qualify_frozen_universe
from quant_stack.models import Exchange, PriceBasis
from quant_stack.snapshot import create_raw_snapshot
from quant_stack.validation import load_daily_bars_csv

app = typer.Typer(help="Offline-first quantitative research commands.")
data_app = typer.Typer(help="Validate and snapshot local data.")
calendar_app = typer.Typer(help="Validate local exchange calendar snapshots.")
backtest_app = typer.Typer(help="Backtest commands (M0 placeholders).")
signal_app = typer.Typer(help="Signal commands (M0 placeholders).")
paper_app = typer.Typer(help="Paper-trading commands (M0 placeholders).")

app.add_typer(data_app, name="data")
app.add_typer(calendar_app, name="calendar")
app.add_typer(backtest_app, name="backtest")
app.add_typer(signal_app, name="signal")
app.add_typer(paper_app, name="paper")

UniverseOption = Annotated[Path, typer.Option(..., exists=True, readable=True)]
RequiredDateOption = Annotated[str, typer.Option(...)]
DataRootOption = Annotated[Path, typer.Option()]
CalendarRootOption = Annotated[Path, typer.Option(exists=True, readable=True)]
AllowNetworkOption = Annotated[bool, typer.Option()]


@data_app.command("validate")
def validate_data(path: Path) -> None:
    """Validate a local daily-bar CSV against the M0 schema."""
    bars = load_daily_bars_csv(path)
    typer.echo(f"valid bars: {len(bars)}")


@data_app.command("qualify-universe")
def qualify_universe(
    universe: UniverseOption,
    data_root: DataRootOption = Path("data"),
    ledger_root: Annotated[Path, typer.Option(exists=True, readable=True)] = Path(
        "configs/corporate_actions"
    ),
    calendar_root: CalendarRootOption = Path("configs/calendars"),
    artifact_root: Annotated[Path, typer.Option()] = Path("artifacts/data_qualification"),
) -> None:
    """Qualify every frozen-universe asset and refuse promotion when any D0 gate is unmet."""
    try:
        report = qualify_frozen_universe(universe, data_root, ledger_root, calendar_root)
        path = persist_qualification_report(report, artifact_root)
    except ValueError as error:
        typer.echo(f"universe qualification failed: {error}", err=True)
        raise typer.Exit(code=1) from error
    typer.echo(f"qualification report: {path}")
    for asset in report.assets:
        typer.echo(f"{asset.symbol}: {asset.result}; reasons={','.join(asset.reasons) or 'none'}")
    if not report.all_qualified:
        raise typer.Exit(code=1)


@data_app.command("snapshot")
def snapshot_data(path: Path, raw_root: Path) -> None:
    """Create an immutable, content-addressed snapshot from a local file."""
    snapshot_path, manifest = create_raw_snapshot(raw_root, path, source="local-file")
    typer.echo(f"snapshot: {manifest.snapshot_id}")
    typer.echo(f"path: {snapshot_path}")


@data_app.command("ingest-etf")
def ingest_etf(
    universe: UniverseOption,
    start: RequiredDateOption,
    as_of: RequiredDateOption,
    data_root: DataRootOption = Path("data"),
    calendar_root: CalendarRootOption = Path("configs/calendars"),
    allow_network: AllowNetworkOption = False,
) -> None:
    """Ingest missing raw and qfq ETF sessions through the explicit network boundary."""
    if not allow_network:
        raise typer.BadParameter("--allow-network is required for AKShare ingestion")
    start_date = _parse_cli_date(start, "start")
    as_of_date = _parse_cli_date(as_of, "as-of")
    try:
        result = ingest_universe(
            load_etf_universe(universe),
            start_date,
            as_of_date,
            data_root,
            ExchangeCalendarStore(calendar_root),
            AKShareETFAdapter(),
        )
    except (
        CalendarNotFoundError,
        CalendarSourceError,
        CoverageError,
        DataFetchError,
        EvidenceArchiveError,
        IncompleteSessionError,
        ValueError,
    ) as error:
        typer.echo(f"ingestion failed: {error}", err=True)
        raise typer.Exit(code=1) from error
    typer.echo(f"immutable ingestions: {len(result.ingestions)}")
    typer.echo(f"coverage reports: {len(result.coverage_reports)} complete")
    for ingestion in result.ingestions:
        typer.echo(f"manifest: {ingestion.manifest_path}")


@data_app.command("capture-non-trading-evidence")
def capture_non_trading_evidence_command(
    universe: UniverseOption,
    data_root: DataRootOption = Path("data"),
    allow_network: AllowNetworkOption = False,
) -> None:
    """Explicitly fetch and hash-check configured official non-trading evidence documents."""
    if not allow_network:
        raise typer.BadParameter("--allow-network is required to capture non-trading evidence")
    events = tuple(
        event
        for instrument in load_etf_universe(universe).instruments
        for event in instrument.documented_non_trading_events
    )
    try:
        paths = capture_non_trading_evidence(events, data_root)
    except EvidenceArchiveError as error:
        typer.echo(f"non-trading evidence capture failed: {error}", err=True)
        raise typer.Exit(code=1) from error
    typer.echo(f"verified non-trading evidence archives: {len(paths)}")


@data_app.command("capture-corporate-action-evidence")
def capture_corporate_action_evidence_command(
    ledger: Annotated[Path, typer.Option(..., exists=True, readable=True)],
    data_root: DataRootOption = Path("data"),
    allow_network: AllowNetworkOption = False,
) -> None:
    """Explicitly capture and verify the official source bodies named by one action ledger."""
    if not allow_network:
        raise typer.BadParameter("--allow-network is required to capture corporate-action evidence")
    try:
        paths = capture_corporate_action_evidence(
            load_corporate_action_ledger(ledger).events,
            data_root,
        )
    except (CorporateActionLedgerError, EvidenceArchiveError) as error:
        typer.echo(f"corporate-action evidence capture failed: {error}", err=True)
        raise typer.Exit(code=1) from error
    typer.echo(f"verified corporate-action evidence archives: {len(paths)}")


@data_app.command("archive-corporate-action-source")
def archive_corporate_action_source_command(
    url: Annotated[str, typer.Option(...)],
    data_root: DataRootOption = Path("data"),
    allow_network: AllowNetworkOption = False,
) -> None:
    """Archive a first-party corporate-action source and print its identity for ledger review."""
    if not allow_network:
        raise typer.BadParameter("--allow-network is required to archive corporate-action evidence")
    try:
        evidence = archive_corporate_action_source(url, data_root)
    except EvidenceArchiveError as error:
        typer.echo(f"corporate-action source archive failed: {error}", err=True)
        raise typer.Exit(code=1) from error
    typer.echo(f"evidence sha256: {evidence.sha256}")


@data_app.command("ingest-szse-raw")
def ingest_szse_raw(
    universe: UniverseOption,
    start: RequiredDateOption,
    as_of: RequiredDateOption,
    symbol: Annotated[str, typer.Option()] = "159919",
    data_root: DataRootOption = Path("data"),
    calendar_root: CalendarRootOption = Path("configs/calendars"),
    allow_network: AllowNetworkOption = False,
) -> None:
    """Capture a provider-native SZSE raw series; no adjusted values are requested or created."""
    if not allow_network:
        raise typer.BadParameter("--allow-network is required for SZSE ingestion")
    start_date = _parse_cli_date(start, "start")
    as_of_date = _parse_cli_date(as_of, "as-of")
    try:
        instruments = load_etf_universe(universe).instruments
        instrument = next(
            item for item in instruments if item.symbol == symbol and item.exchange is Exchange.SZSE
        )
        calendar = ExchangeCalendarStore(calendar_root)
        calendar.require_completed_as_of(instrument.exchange, as_of_date)
        request = ETFHistoryRequest(
            instrument=instrument,
            start_date=max(start_date, instrument.effective_from),
            as_of_date=as_of_date,
            price_basis=PriceBasis.RAW,
        )
        manifest = persist_szse_daily_history(
            request,
            fetch_szse_daily_history(instrument.symbol),
            data_root,
        )
        bars = load_szse_provider_bars(manifest, data_root)
        coverage = calendar.coverage_report(
            instrument,
            PriceBasis.RAW,
            {bar.trading_date for bar in bars},
            request.start_date,
            request.as_of_date,
        )
    except (
        CalendarNotFoundError,
        CalendarSourceError,
        IncompleteSessionError,
        SZSEProviderError,
        StopIteration,
        ValueError,
    ) as error:
        typer.echo(f"SZSE ingestion failed: {error}", err=True)
        raise typer.Exit(code=1) from error
    typer.echo(f"provider manifest: {manifest.manifest_id}")
    typer.echo(f"raw provider rows: {len(bars)}")
    typer.echo(f"coverage complete: {coverage.is_complete}")
    if not coverage.is_complete:
        typer.echo(
            "SZSE provider series is retained but cannot pass the Issue 003 coverage gate", err=True
        )
        raise typer.Exit(code=1)


@data_app.command("audit-szse-history")
def audit_szse_history(
    universe: UniverseOption,
    start: RequiredDateOption,
    as_of: RequiredDateOption,
    symbol: Annotated[str, typer.Option()] = "159919",
    data_root: DataRootOption = Path("data"),
    allow_network: AllowNetworkOption = False,
) -> None:
    """Record three bounded official SZSE parameter probes without creating canonical data."""
    if not allow_network:
        raise typer.BadParameter("--allow-network is required for SZSE history auditing")
    start_date = _parse_cli_date(start, "start")
    as_of_date = _parse_cli_date(as_of, "as-of")
    probes = {
        "base": {},
        "pagination": {"page": "2", "pageSize": "5000"},
        "date_window": {"beginDate": start_date.isoformat(), "endDate": as_of_date.isoformat()},
    }
    try:
        instrument = next(
            item
            for item in load_etf_universe(universe).instruments
            if item.symbol == symbol and item.exchange is Exchange.SZSE
        )
        request = ETFHistoryRequest(
            instrument=instrument,
            start_date=max(start_date, instrument.effective_from),
            as_of_date=as_of_date,
            price_basis=PriceBasis.RAW,
        )
        summaries = []
        for name, parameters in probes.items():
            manifest = persist_szse_daily_history(
                request,
                fetch_szse_daily_history(instrument.symbol, parameters),
                data_root,
            )
            summaries.append(
                {
                    "probe": name,
                    "manifest_id": manifest.manifest_id,
                    "request_parameters": manifest.request_parameters,
                    "row_count": manifest.row_count,
                    "first_trading_date": manifest.first_trading_date.isoformat(),
                    "last_trading_date": manifest.last_trading_date.isoformat(),
                }
            )
    except (SZSEProviderError, StopIteration, ValueError) as error:
        typer.echo(f"SZSE history audit failed: {error}", err=True)
        raise typer.Exit(code=1) from error
    typer.echo(json.dumps(summaries, ensure_ascii=False, indent=2))


@data_app.command("reattest-szse-raw")
def reattest_szse_raw(
    manifest: Annotated[Path, typer.Option(..., exists=True, readable=True)],
    universe: UniverseOption,
    start: RequiredDateOption,
    as_of: RequiredDateOption,
    data_root: DataRootOption = Path("data"),
) -> None:
    """Re-normalize a retained SZSE raw response under the current parser without network access."""
    start_date = _parse_cli_date(start, "start")
    as_of_date = _parse_cli_date(as_of, "as-of")
    try:
        source_manifest = ProviderSeriesManifest.model_validate_json(
            manifest.read_text(encoding="utf-8")
        )
        instrument = next(
            item
            for item in load_etf_universe(universe).instruments
            if (
                item.symbol == source_manifest.instrument.symbol
                and item.exchange is source_manifest.instrument.exchange
            )
        )
        result = reattest_szse_daily_history(
            ETFHistoryRequest(
                instrument=instrument,
                start_date=max(start_date, instrument.effective_from),
                as_of_date=as_of_date,
                price_basis=PriceBasis.RAW,
            ),
            source_manifest,
            data_root,
        )
    except (SZSEProviderError, StopIteration, ValueError) as error:
        typer.echo(f"SZSE re-attestation failed: {error}", err=True)
        raise typer.Exit(code=1) from error
    typer.echo(f"provider manifest: {result.manifest_id}")


@data_app.command("capture-sina-adjustment-candidate")
def capture_sina_adjustment_candidate(
    symbol: Annotated[str, typer.Option()] = "159919",
    data_root: DataRootOption = Path("data"),
    allow_network: AllowNetworkOption = False,
) -> None:
    """Capture a Sina factor candidate for audit only; it cannot publish qfq data."""
    if not allow_network:
        raise typer.BadParameter("--allow-network is required for Sina adjustment capture")
    try:
        path = persist_sina_adjustment_candidate(fetch_sina_adjustment_candidate(symbol), data_root)
    except SinaProviderError as error:
        typer.echo(f"Sina adjustment candidate failed: {error}", err=True)
        raise typer.Exit(code=1) from error
    typer.echo(f"candidate path: {path}")


@data_app.command("ingest-sina-raw")
def ingest_sina_raw(
    universe: UniverseOption,
    start: RequiredDateOption,
    as_of: RequiredDateOption,
    symbol: Annotated[str, typer.Option()] = "159919",
    data_root: DataRootOption = Path("data"),
    calendar_root: CalendarRootOption = Path("configs/calendars"),
    allow_network: AllowNetworkOption = False,
) -> None:
    """Capture an independent Sina raw series; it is never joined to another provider."""
    if not allow_network:
        raise typer.BadParameter("--allow-network is required for Sina ingestion")
    start_date = _parse_cli_date(start, "start")
    as_of_date = _parse_cli_date(as_of, "as-of")
    try:
        instrument = next(
            item
            for item in load_etf_universe(universe).instruments
            if item.symbol == symbol and item.exchange is Exchange.SZSE
        )
        calendar = ExchangeCalendarStore(calendar_root)
        calendar.require_completed_as_of(instrument.exchange, as_of_date)
        request = ETFHistoryRequest(
            instrument=instrument,
            start_date=max(start_date, instrument.effective_from),
            as_of_date=as_of_date,
            price_basis=PriceBasis.RAW,
        )
        manifest = persist_sina_etf_history(
            request,
            fetch_sina_etf_history(instrument.symbol),
            data_root,
        )
        bars = load_sina_provider_bars(manifest, data_root)
        coverage = calendar.coverage_report(
            instrument,
            PriceBasis.RAW,
            {bar.trading_date for bar in bars},
            request.start_date,
            request.as_of_date,
        )
    except (
        CalendarNotFoundError,
        CalendarSourceError,
        IncompleteSessionError,
        SinaProviderError,
        StopIteration,
        ValueError,
    ) as error:
        typer.echo(f"Sina ingestion failed: {error}", err=True)
        raise typer.Exit(code=1) from error
    typer.echo(f"provider manifest: {manifest.manifest_id}")
    typer.echo(f"raw provider rows: {len(bars)}")
    typer.echo(f"coverage complete: {coverage.is_complete}")
    if not coverage.is_complete:
        typer.echo(
            "Sina provider series is retained but cannot pass the Issue 003 coverage gate", err=True
        )
        raise typer.Exit(code=1)


@data_app.command("coverage")
def show_coverage(
    universe: UniverseOption,
    start: RequiredDateOption,
    as_of: RequiredDateOption,
    data_root: DataRootOption = Path("data"),
    calendar_root: CalendarRootOption = Path("configs/calendars"),
) -> None:
    """Report local raw and qfq coverage without accessing the network."""
    start_date = _parse_cli_date(start, "start")
    as_of_date = _parse_cli_date(as_of, "as-of")
    calendar = ExchangeCalendarStore(calendar_root)
    try:
        reports = []
        for instrument in load_etf_universe(universe).instruments:
            if instrument.effective_from > as_of_date:
                continue
            bounded_start = max(start_date, instrument.effective_from)
            bounded_end = min(as_of_date, instrument.effective_to or as_of_date)
            calendar.require_completed_as_of(instrument.exchange, bounded_end)
            require_non_trading_evidence(instrument.documented_non_trading_events, data_root)
            for price_basis in (PriceBasis.RAW, PriceBasis.QFQ):
                reports.append(
                    calendar.coverage_report(
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
                    )
                )
    except (
        CalendarNotFoundError,
        CalendarSourceError,
        EvidenceArchiveError,
        IncompleteSessionError,
        ProvenanceError,
        ValueError,
    ) as error:
        typer.echo(f"coverage check failed: {error}", err=True)
        raise typer.Exit(code=1) from error
    summaries = [
        {
            "instrument": f"{report.instrument.exchange.value}:{report.instrument.symbol}",
            "price_basis": report.price_basis.value,
            "present_session_count": len(report.present_dates),
            "coverage_complete": report.is_complete,
            "missing": [
                {"trading_date": record.trading_date.isoformat(), "kind": record.kind.value}
                for record in report.missing
            ],
            "documented_non_trading": [
                {
                    "trading_date": record.trading_date.isoformat(),
                    "reason": record.reason,
                    "evidence_sha256": record.evidence.sha256,
                }
                for record in report.documented_non_trading
            ],
        }
        for report in reports
    ]
    typer.echo(json.dumps(summaries, ensure_ascii=False, indent=2))
    if any(not report.is_complete for report in reports):
        raise typer.Exit(code=1)


@data_app.command("verify")
def verify_data(path: Path, data_root: DataRootOption = Path("data")) -> None:
    """Verify one normalized Parquet file against its immutable raw source and manifest."""
    try:
        manifest = verify_normalized_parquet(path, data_root)
    except (EvidenceArchiveError, ProvenanceError) as error:
        typer.echo(f"verification failed: {error}", err=True)
        raise typer.Exit(code=1) from error
    typer.echo(f"verified manifest: {manifest.manifest_id}")


@calendar_app.command("validate")
def validate_calendar(
    exchange: Annotated[str, typer.Option(...)],
    year: Annotated[int, typer.Option(min=1990, max=2100)],
    calendar_root: CalendarRootOption = Path("configs/calendars"),
    verify_sources: AllowNetworkOption = False,
    data_root: DataRootOption = Path("data"),
) -> None:
    """Validate one local annual calendar snapshot and display its session count."""
    from quant_stack.models import Exchange

    try:
        parsed_exchange = Exchange(exchange.upper())
    except ValueError as error:
        raise typer.BadParameter("exchange must be SSE or SZSE") from error
    if parsed_exchange is Exchange.TEST:
        raise typer.BadParameter("exchange must be SSE or SZSE")
    store = ExchangeCalendarStore(calendar_root)
    calendar = store.load_year(parsed_exchange, year)
    if verify_sources:
        store.require_source_archives(
            parsed_exchange,
            date(year, 1, 1),
            date(year, 12, 31),
            data_root,
        )
    typer.echo(f"{calendar.exchange.value} {calendar.year}: {len(calendar.sessions)} sessions")


@calendar_app.command("capture-sources")
def capture_calendar_sources(
    start_year: Annotated[int, typer.Option(min=1990, max=2100)],
    end_year: Annotated[int, typer.Option(min=1990, max=2100)],
    calendar_root: CalendarRootOption = Path("configs/calendars"),
    data_root: DataRootOption = Path("data"),
    allow_network: AllowNetworkOption = False,
) -> None:
    """Explicitly fetch and hash-check official notices into the local raw archive."""
    from quant_stack.models import Exchange

    if not allow_network:
        raise typer.BadParameter("--allow-network is required to capture calendar sources")
    if start_year > end_year:
        raise typer.BadParameter("start-year must not exceed end-year")
    store = ExchangeCalendarStore(calendar_root)
    try:
        paths = [
            path
            for exchange in (Exchange.SSE, Exchange.SZSE)
            for path in store.capture_source_archives(
                exchange,
                date(start_year, 1, 1),
                date(end_year, 12, 31),
                data_root,
            )
        ]
    except (CalendarNotFoundError, CalendarSourceError) as error:
        typer.echo(f"calendar source capture failed: {error}", err=True)
        raise typer.Exit(code=1) from error
    typer.echo(f"verified calendar source archives: {len(paths)}")


def _m0_placeholder(capability: str) -> None:
    """State an unimplemented boundary without performing financial actions."""
    typer.echo(f"{capability} is not implemented in M0; no action was taken")


def _parse_cli_date(value: str, option_name: str) -> date:
    """Parse an explicit local trading-date boundary from the CLI."""
    try:
        return date.fromisoformat(value)
    except ValueError as error:
        raise typer.BadParameter(f"{option_name} must use YYYY-MM-DD") from error


@backtest_app.command("run")
def run_backtest() -> None:
    """Reserve the future backtest interface."""
    _m0_placeholder("backtest")


@signal_app.command("generate")
def generate_signal() -> None:
    """Reserve the future signal interface."""
    _m0_placeholder("signal generation")


@paper_app.command("reconcile")
def reconcile_paper() -> None:
    """Reserve the future paper-ledger reconciliation interface."""
    _m0_placeholder("paper reconciliation")


if __name__ == "__main__":
    app()
