from datetime import date
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace

import pandas as pd
import pytest

import quant_stack.paper_service as paper_service
from quant_stack.models import DailyBar, Exchange, PriceBasis
from quant_stack.paper_service import PaperDailyError, load_paper_environment, run_paper_daily


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

    class Calendar:
        def is_session(self, _exchange: Exchange, _day: date) -> bool:
            return True

        def next_session(self, _exchange: Exchange, day: date) -> date:
            return (pd.Timestamp(day) + pd.offsets.BDay(1)).date()

        def coverage_report(self, *_args: object, **_kwargs: object) -> SimpleNamespace:
            return SimpleNamespace(is_complete=True)

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
    monkeypatch.setattr(
        paper_service,
        "_refresh_primary_raw",
        lambda *_args: ({symbol: SimpleNamespace(manifest_id=symbol) for symbol in raw}, raw),
    )
    monkeypatch.setattr(paper_service, "_causal_for_paper", lambda bars, _ledger: bars)
    monkeypatch.setattr(paper_service, "require_corporate_action_evidence", lambda *_: None)
    first = run_paper_daily(
        environment,
        tmp_path / "data",
        tmp_path / "artifacts",
        date(2026, 1, 30),
        allow_network=True,
    )
    second = run_paper_daily(
        environment, tmp_path / "data", tmp_path / "artifacts", date(2026, 2, 2), allow_network=True
    )
    assert first.is_file() and second.is_file()
    broker = paper_service.initialize_paper_account(environment, tmp_path / "artifacts")
    assert broker.fills()
    assert "NO_EVIDENCE_OF_EDGE" in second.read_text(encoding="utf-8")
