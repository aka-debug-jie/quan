"""Offline regression coverage for the forward-only CSI300 shadow loop."""

from __future__ import annotations

import json
from datetime import UTC, date, datetime
from pathlib import Path

from quant_stack.data.calendar import ExchangeCalendarStore
from quant_stack.models import Exchange
from quant_stack_v2.prospective_diagnostics import build_diagnostics
from quant_stack_v2.prospective_runner import rebuild_status
from quant_stack_v2.prospective_shadow import (
    archive_snapshot_payload,
    build_signal,
    load_config,
    run_paper_day,
)

ROOT = Path(__file__).parents[1]


def test_prospective_signal_paper_and_delayed_diagnostics(tmp_path: Path) -> None:
    config_path = ROOT / "configs/v2/prospective/cn_shadow_v1.yaml"
    config = load_config(config_path)
    calendar = ExchangeCalendarStore(ROOT / "configs/calendars")
    sessions = calendar.sessions_between(Exchange.SSE, date(2026, 1, 1), date(2026, 6, 30))[:63]
    receipts: list[Path] = []
    for offset, session in enumerate(sessions):
        records = []
        for index in range(205):
            symbol = f"sh{600000 + index:06d}"
            price = 10 + index / 50 + offset * ((index % 7) + 1) / 1000
            previous = 10 + index / 50 + max(0, offset - 1) * ((index % 7) + 1) / 1000
            records.append(
                {
                    "symbol": symbol,
                    "name": f"fixture-{index}",
                    "open": price,
                    "high": price + 0.2 + (index % 3) / 100,
                    "low": price - 0.2,
                    "close": price + (index % 5) / 100,
                    "previous_close": previous,
                    "volume": 1_000_000 + index * 100 + offset,
                    "amount": 20_000_000 + index * 1000,
                    "member": True,
                    "st": False,
                    "suspended": False,
                    "exchange": "SSE",
                    "board": "main",
                }
            )
        receipts.append(
            archive_snapshot_payload(
                {
                    "schema_version": 2,
                    "trading_date": session.isoformat(),
                    "captured_at": datetime(
                        session.year, session.month, session.day, 8, 30, tzinfo=UTC
                    ).isoformat(),
                    "observation_mode": "PROSPECTIVE",
                    "records": records,
                    "corporate_actions": [],
                    "benchmark": {"close": 4000 + offset},
                },
                tmp_path / "data",
                provider="fixture",
            )
        )
    artifacts = tmp_path / "artifacts"
    signal = json.loads(build_signal(config, receipts[59], artifacts).read_text())
    assert signal["INPUT_STATUS"] == "FULLY_PROSPECTIVE_INPUT"
    assert signal["SHADOW_SIGNAL_STATUS"] == "SIGNAL_EMITTED"
    assert len(signal["top"]) == 20
    first = json.loads(
        run_paper_day(
            config,
            receipts[59],
            artifacts,
            calendar_root=ROOT / "configs/calendars",
            rules_path=ROOT / "configs/v2/prospective/cn_shadow_rules_v1.yaml",
        ).read_text()
    )
    second = json.loads(
        run_paper_day(
            config,
            receipts[60],
            artifacts,
            calendar_root=ROOT / "configs/calendars",
            rules_path=ROOT / "configs/v2/prospective/cn_shadow_rules_v1.yaml",
        ).read_text()
    )
    assert first["fills_today"] == 0
    assert second["fills_today"] > 0
    diagnostics = json.loads(
        build_diagnostics(tmp_path / "data", artifacts, sessions[62], config=config).read_text()
    )
    assert len(diagnostics["days"]) == 1
    assert diagnostics["SHADOW_SIGNAL_STATUS"] == "INSUFFICIENT_LABELS"
    rebuilt = rebuild_status(config_path, artifacts, through=sessions[60])
    assert rebuilt["PAPER_ACCOUNT_STATUS"] == "RECONCILED_LOCAL_ONLY"


def test_cash_distribution_keeps_feature_price_continuous(tmp_path: Path) -> None:
    from quant_stack_v2.prospective_shadow import _history

    sessions = (date(2026, 1, 5), date(2026, 1, 6))
    closes = (10.0, 9.0)
    for index, session in enumerate(sessions):
        archive_snapshot_payload(
            {
                "trading_date": session.isoformat(),
                "captured_at": f"{session.isoformat()}T08:30:00+00:00",
                "observation_mode": "PROSPECTIVE",
                "records": [
                    {
                        "symbol": "sh600000",
                        "open": closes[index],
                        "high": closes[index],
                        "low": closes[index],
                        "close": closes[index],
                        "previous_close": closes[max(0, index - 1)],
                        "volume": 1000,
                        "amount": 20_000_000,
                        "member": True,
                        "st": False,
                        "suspended": False,
                        "exchange": "SSE",
                        "board": "main",
                    }
                ],
                "corporate_actions": [
                    {
                        "symbol": "sh600000",
                        "announcement_date": "2025-12-01",
                        "effective_date": "2026-01-06",
                        "record_date": "2026-01-05",
                        "payment_date": "2026-01-06",
                        "source_url": "https://example.test/action",
                        "source_sha256": "a" * 64,
                        "kind": "cash_distribution",
                        "cash_per_unit": 1.0,
                    }
                ],
            },
            tmp_path,
            provider="fixture",
        )
    history = _history(tmp_path, sessions[-1])
    assert history.calc_close.tolist() == [10.0, 10.0]
