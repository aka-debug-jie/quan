from datetime import date
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace

import pandas as pd
import pytest

import quant_stack.paper_service as paper_service
from quant_stack.models import DailyBar, Exchange, PriceBasis
from quant_stack.paper_service import (
    PaperDailyError,
    load_paper_environment,
    run_paper_catchup,
    run_paper_daily,
)


def test_paper_environment_rejects_live_order_capability(tmp_path: Path) -> None:
    environment = tmp_path / "paper.yaml"
    environment.write_text("mode: paper\nallow_live_orders: true\n", encoding="utf-8")
    with pytest.raises(PaperDailyError, match="forbid live orders"):
        load_paper_environment(environment)


def test_paper_daily_requires_explicit_network_authorization(tmp_path: Path) -> None:
    environment = tmp_path / "paper.yaml"
    environment.write_text(
        "mode: paper\nallow_live_orders: false\nallow_network_data_download: true\n",
        encoding="utf-8",
    )
    with pytest.raises(PaperDailyError, match="explicit network"):
        run_paper_daily(
            environment,
            tmp_path / "data",
            tmp_path / "artifacts",
            date(2026, 1, 2),
            allow_network=False,
        )


def test_failed_daily_run_leaves_a_failure_receipt(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    environment = tmp_path / "paper.yaml"
    environment.write_text(
        "mode: paper\nallow_live_orders: false\nallow_network_data_download: true\n",
        encoding="utf-8",
    )

    def fail(*_args: object, **_kwargs: object) -> Path:
        raise PaperDailyError("offline provider")

    monkeypatch.setattr(paper_service, "_run_paper_daily_locked", fail)
    with pytest.raises(PaperDailyError, match="offline provider"):
        run_paper_daily(
            environment,
            tmp_path / "data",
            tmp_path / "artifacts",
            date(2026, 1, 2),
            allow_network=True,
        )
    assert list((tmp_path / "artifacts" / "failures").glob("*.json"))


def test_daily_paper_run_writes_report_and_fills_prior_order(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = Path(__file__).resolve().parents[1]
    dates = pd.bdate_range("2025-01-02", "2026-02-02")
    symbols = {"510300": Exchange.SSE, "510500": Exchange.SSE, "159919": Exchange.SZSE}
    raw = {
        symbol: [
            DailyBar(
                symbol=symbol,
                exchange=exchange,
                price_basis=PriceBasis.RAW,
                trading_date=item.date(),
                open=Decimal("10") + Decimal(index) / Decimal("100"),
                high=Decimal("10.1") + Decimal(index) / Decimal("100"),
                low=Decimal("9.9") + Decimal(index) / Decimal("100"),
                close=Decimal("10") + Decimal(index) / Decimal("100"),
                volume=Decimal("1000"),
            )
            for index, item in enumerate(dates)
        ]
        for symbol, exchange in symbols.items()
    }
    coverage_ok = [False]

    class Calendar:
        def is_session(self, _exchange: Exchange, _day: date) -> bool:
            return True

        def next_session(self, _exchange: Exchange, day: date) -> date:
            return (pd.Timestamp(day) + pd.offsets.BDay(1)).date()

        def coverage_report(self, *_args: object, **_kwargs: object) -> SimpleNamespace:
            return SimpleNamespace(is_complete=coverage_ok[0])

    environment = tmp_path / "paper.yaml"
    environment.write_text(
        "\n".join(
            (
                "mode: paper",
                "allow_live_orders: false",
                "allow_network_data_download: true",
                "account_id: test-paper",
                "initial_cash: '100000'",
                f"universe: {root / 'configs/assets/etf_universe_v2.yaml'}",
                f"source_registry: {root / 'configs/data_qualification/d0_sources_v1.yaml'}",
                f"ledger_root: {root / 'configs/corporate_actions'}",
                f"calendar_root: {tmp_path}",
                f"cost_config: {root / 'configs/costs/cn_etf_v1.yaml'}",
            )
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(paper_service, "ExchangeCalendarStore", lambda _path: Calendar())
    refresh_calls: list[date] = []

    def refresh(*_args: object) -> tuple[dict[str, object], dict[str, list[DailyBar]]]:
        refresh_calls.append(_args[2])
        return (
            {
                symbol: SimpleNamespace(
                    manifest_id=symbol, instrument=SimpleNamespace(symbol=symbol)
                )
                for symbol in raw
            },
            raw,
        )

    monkeypatch.setattr(paper_service, "_refresh_primary_raw", refresh)
    monkeypatch.setattr(
        paper_service,
        "load_provider_series",
        lambda manifest_id, _root: (
            SimpleNamespace(
                manifest_id=manifest_id,
                instrument=SimpleNamespace(symbol=manifest_id),
            ),
            raw[manifest_id],
        ),
    )
    monkeypatch.setattr(paper_service, "_causal_for_paper", lambda bars, _ledger: bars)
    monkeypatch.setattr(paper_service, "require_corporate_action_evidence", lambda *_: None)
    with pytest.raises(PaperDailyError, match="unresolved expected sessions"):
        run_paper_daily(
            environment,
            tmp_path / "data",
            tmp_path / "artifacts",
            date(2026, 1, 28),
            allow_network=True,
        )
    assert not (tmp_path / "artifacts/test-paper/prepared/2026-01-28.json").exists()
    coverage_ok[0] = True
    recovered_input = run_paper_daily(
        environment,
        tmp_path / "data",
        tmp_path / "artifacts",
        date(2026, 1, 28),
        allow_network=True,
    )
    assert recovered_input.is_file()
    assert (tmp_path / "artifacts/test-paper/prepared/2026-01-28.json").is_file()
    mid_month = run_paper_daily(
        environment,
        tmp_path / "data",
        tmp_path / "artifacts",
        date(2026, 1, 29),
        allow_network=True,
    )
    broker = paper_service.initialize_paper_account(environment, tmp_path / "artifacts")
    assert mid_month.is_file()
    assert not broker.orders()
    original_write = paper_service.write_paper_report

    def fail_report(*_args: object, **_kwargs: object) -> Path:
        raise OSError("synthetic report failure")

    monkeypatch.setattr(paper_service, "write_paper_report", fail_report)
    with pytest.raises(OSError, match="synthetic report failure"):
        run_paper_daily(
            environment,
            tmp_path / "data",
            tmp_path / "artifacts",
            date(2026, 1, 30),
            allow_network=True,
        )
    assert not (tmp_path / "artifacts/test-paper/completed/2026-01-30.json").exists()
    monkeypatch.setattr(paper_service, "write_paper_report", original_write)
    first = run_paper_daily(
        environment,
        tmp_path / "data",
        tmp_path / "artifacts",
        date(2026, 1, 30),
        allow_network=True,
    )
    assert refresh_calls.count(date(2026, 1, 30)) == 1
    second = run_paper_daily(
        environment, tmp_path / "data", tmp_path / "artifacts", date(2026, 2, 2), allow_network=True
    )
    assert first.is_file() and second.is_file()
    assert (tmp_path / "artifacts/test-paper/completed/2026-01-30.json").is_file()
    assert broker.fills()
    assert "NO_EVIDENCE_OF_EDGE" in second.read_text(encoding="utf-8")


def test_catchup_marks_historical_sessions_without_backdating_generation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    environment = tmp_path / "paper.yaml"
    environment.write_text(
        "mode: paper\nallow_live_orders: false\naccount_id: test-paper\nuniverse: universe.yaml\n"
        "calendar_root: calendars\n",
        encoding="utf-8",
    )
    broker = SimpleNamespace()
    instrument = SimpleNamespace(exchange=Exchange.SSE)

    class Calendar:
        def sessions_between(self, _exchange: Exchange, start: date, end: date) -> tuple[date, ...]:
            values = (date(2026, 1, 29), date(2026, 1, 30), date(2026, 2, 2))
            return tuple(item for item in values if start <= item <= end)

        def is_session(self, *_args: object) -> bool:
            return True

    recorded: list[tuple[date, object, bool]] = []

    def record(*_args: object, **kwargs: object) -> Path:
        session = _args[3]
        assert isinstance(session, date)
        recorded.append((session, kwargs["generated_at"], bool(kwargs["is_backfill"])))
        return tmp_path / f"{session}.html"

    monkeypatch.setattr(paper_service, "initialize_paper_account", lambda *_: broker)
    monkeypatch.setattr(paper_service, "_universe", lambda *_: (instrument,))
    monkeypatch.setattr(paper_service, "ExchangeCalendarStore", lambda *_: Calendar())
    monkeypatch.setattr(paper_service, "run_paper_daily", record)
    pending = tmp_path / "artifacts/test-paper/pending"
    pending.mkdir(parents=True)
    (pending / "2026-01-30.json").write_text("{}", encoding="utf-8")
    run_paper_catchup(
        environment,
        tmp_path / "data",
        tmp_path / "artifacts",
        date(2026, 2, 2),
        allow_network=True,
    )
    assert [(item[0], item[2]) for item in recorded] == [
        (date(2026, 1, 30), True),
        (date(2026, 2, 2), False),
    ]
    assert recorded[0][1] == recorded[1][1]
