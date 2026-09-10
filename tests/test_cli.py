from pathlib import Path

import pytest
from typer.testing import CliRunner

import quant_stack.cli as cli
from quant_stack.data.akshare_etf import DataFetchError
from quant_stack.data.ingest import UniverseIngestionResult

FIXTURE = Path(__file__).parent / "fixtures" / "synthetic_etf_daily.csv"
CALENDARS = Path(__file__).parent / "fixtures" / "calendars"
runner = CliRunner()


def test_data_validate_command() -> None:
    result = runner.invoke(cli.app, ["data", "validate", str(FIXTURE)])
    assert result.exit_code == 0
    assert "valid bars: 6" in result.stdout


def test_universe_qualification_refuses_promotion_for_unqualified_assets(tmp_path: Path) -> None:
    result = runner.invoke(
        cli.app,
        [
            "data",
            "qualify-universe",
            "--universe",
            "configs/assets/etf_universe_v1.yaml",
            "--data-root",
            str(tmp_path / "data"),
            "--calendar-root",
            str(CALENDARS),
            "--artifact-root",
            str(tmp_path / "artifacts"),
        ],
    )
    assert result.exit_code == 1
    assert "510300: NOT_QUALIFIED" in result.stdout


def test_backtest_is_explicit_placeholder() -> None:
    result = runner.invoke(cli.app, ["backtest", "run"])
    assert result.exit_code == 0
    assert "not implemented in M0" in result.stdout


def test_etf_ingestion_requires_explicit_network_permission() -> None:
    result = runner.invoke(
        cli.app,
        [
            "data",
            "ingest-etf",
            "--universe",
            "configs/assets/etf_universe_v1.yaml",
            "--start",
            "2015-01-01",
            "--as-of",
            "2024-01-04",
        ],
    )

    assert result.exit_code != 0
    assert "--allow-network is required" in result.output


def test_calendar_validation_uses_local_snapshot() -> None:
    result = runner.invoke(
        cli.app,
        [
            "calendar",
            "validate",
            "--exchange",
            "SSE",
            "--year",
            "2024",
            "--calendar-root",
            str(CALENDARS),
        ],
    )

    assert result.exit_code == 0
    assert "SSE 2024: 5 sessions" in result.stdout


def test_coverage_command_reports_compact_missing_summary(tmp_path: Path) -> None:
    result = runner.invoke(
        cli.app,
        [
            "data",
            "coverage",
            "--universe",
            "configs/assets/etf_universe_v1.yaml",
            "--start",
            "2015-01-01",
            "--as-of",
            "2024-01-04",
            "--data-root",
            str(tmp_path),
        ],
    )

    assert result.exit_code == 1
    assert '"present_session_count": 0' in result.stdout
    assert '"expected_session_missing"' in result.stdout


def test_ingest_command_reports_expected_fetch_failure_without_traceback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fail(*_: object, **__: object) -> UniverseIngestionResult:
        raise DataFetchError("provider unavailable")

    monkeypatch.setattr(cli, "ingest_universe", fail)
    result = runner.invoke(
        cli.app,
        [
            "data",
            "ingest-etf",
            "--universe",
            "configs/assets/etf_universe_v1.yaml",
            "--start",
            "2015-01-01",
            "--as-of",
            "2024-01-04",
            "--allow-network",
        ],
    )

    assert result.exit_code == 1
    assert "ingestion failed: provider unavailable" in result.output


def test_ingest_command_displays_complete_result(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        cli,
        "ingest_universe",
        lambda *_: UniverseIngestionResult(ingestions=(), coverage_reports=()),
    )
    result = runner.invoke(
        cli.app,
        [
            "data",
            "ingest-etf",
            "--universe",
            "configs/assets/etf_universe_v1.yaml",
            "--start",
            "2015-01-01",
            "--as-of",
            "2024-01-04",
            "--allow-network",
        ],
    )

    assert result.exit_code == 0
    assert "coverage reports: 0 complete" in result.stdout


def test_calendar_source_capture_requires_explicit_network_permission() -> None:
    result = runner.invoke(
        cli.app,
        [
            "calendar",
            "capture-sources",
            "--start-year",
            "2024",
            "--end-year",
            "2024",
        ],
    )

    assert result.exit_code != 0
    assert "--allow-network is required" in result.output


def test_non_trading_evidence_capture_requires_explicit_network_permission() -> None:
    result = runner.invoke(
        cli.app,
        [
            "data",
            "capture-non-trading-evidence",
            "--universe",
            "configs/assets/etf_universe_v2.yaml",
        ],
    )

    assert result.exit_code != 0
    assert "--allow-network is required" in result.output
