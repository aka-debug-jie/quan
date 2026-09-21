"""Offline regression coverage for the forward-only CSI300 shadow loop."""

from __future__ import annotations

import json
from datetime import UTC, date, datetime
from pathlib import Path

import pandas as pd

from quant_stack.data.calendar import ExchangeCalendarStore
from quant_stack.models import Exchange
from quant_stack_v2.prospective_diagnostics import build_diagnostics
from quant_stack_v2.prospective_runner import build_acceptance_manifest, rebuild_status
from quant_stack_v2.prospective_shadow import (
    _history,
    _input_status,
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


def test_full_input_requires_every_scored_symbol_and_exact_calendar_window() -> None:
    config = load_config(ROOT / "configs/v2/prospective/cn_shadow_v1.yaml")
    calendar = ExchangeCalendarStore(ROOT / "configs/calendars")
    sessions = calendar.sessions_between(Exchange.SSE, date(2026, 1, 1), date(2026, 6, 30))[:60]
    mixed = pd.DataFrame(
        [
            {
                "symbol": symbol,
                "session": pd.Timestamp(session),
                "observation_mode": "WARM_START_NON_FORMAL"
                if symbol == "sh600001" and index == 0
                else "PROSPECTIVE",
            }
            for symbol in ("sh600000", "sh600001")
            for index, session in enumerate(sessions)
        ]
    )
    assert (
        _input_status(
            mixed,
            ("sh600000", "sh600001"),
            sessions[-1],
            config,
            ROOT / "configs/calendars",
            "COMPLETE",
        )
        == "MIXED_PROSPECTIVE_INPUT"
    )

    prior = calendar.previous_session(Exchange.SSE, sessions[0])
    gap = pd.DataFrame(
        {
            "symbol": ["sh600000"] * 60,
            "session": [pd.Timestamp(prior), *map(pd.Timestamp, sessions[1:])],
            "observation_mode": ["PROSPECTIVE"] * 60,
        }
    )
    assert (
        _input_status(
            gap,
            ("sh600000",),
            sessions[-1],
            config,
            ROOT / "configs/calendars",
            "COMPLETE",
        )
        == "MIXED_PROSPECTIVE_INPUT"
    )


def test_formal_account_starts_empty_after_mixed_warm_start(tmp_path: Path) -> None:
    config = load_config(ROOT / "configs/v2/prospective/cn_shadow_v1.yaml")
    calendar = ExchangeCalendarStore(ROOT / "configs/calendars")
    sessions = calendar.sessions_between(Exchange.SSE, date(2026, 1, 1), date(2026, 6, 30))[:61]
    receipts: list[Path] = []
    for offset, session in enumerate(sessions):
        records = [
            {
                "symbol": f"sh{600000 + index:06d}",
                "open": 10 + index / 100 + offset / 1000,
                "high": 11 + index / 100 + offset / 1000,
                "low": 9 + index / 100 + offset / 1000,
                "close": 10.2 + index / 100 + offset * ((index % 7) + 1) / 1000,
                "previous_close": 10 + index / 100,
                "volume": 1_000_000 + index + offset,
                "amount": 20_000_000 + index,
                "member": True,
                "st": False,
                "suspended": False,
                "exchange": "SSE",
                "board": "main",
            }
            for index in range(205)
        ]
        receipts.append(
            archive_snapshot_payload(
                {
                    "trading_date": session.isoformat(),
                    "captured_at": datetime(
                        session.year, session.month, session.day, 8, 30, tzinfo=UTC
                    ).isoformat(),
                    "observation_mode": "WARM_START_NON_FORMAL" if offset == 0 else "PROSPECTIVE",
                    "records": records,
                    "corporate_actions": [],
                },
                tmp_path / "data",
                provider="fixture",
            )
        )
    artifacts = tmp_path / "artifacts"
    mixed = json.loads(
        run_paper_day(
            config,
            receipts[59],
            artifacts,
            calendar_root=ROOT / "configs/calendars",
            rules_path=ROOT / "configs/v2/prospective/cn_shadow_rules_v1.yaml",
        ).read_text()
    )
    formal = json.loads(
        run_paper_day(
            config,
            receipts[60],
            artifacts,
            calendar_root=ROOT / "configs/calendars",
            rules_path=ROOT / "configs/v2/prospective/cn_shadow_rules_v1.yaml",
        ).read_text()
    )
    assert mixed["paper_account_phase"] == "engineering_warm_start"
    assert formal["paper_account_phase"] == "fully_prospective_v1"
    assert formal["fills_today"] == 0
    assert formal["cash"] == "1000000"
    assert formal["positions"] == {}


def test_late_action_changes_future_history_without_rewriting_earlier_view(
    tmp_path: Path,
) -> None:
    sessions = (date(2026, 1, 5), date(2026, 1, 6), date(2026, 1, 7))
    receipts: list[Path] = []
    for index, session in enumerate(sessions):
        actions = []
        if index == 2:
            actions = [
                {
                    "symbol": "sh600000",
                    "announcement_date": "2026-01-07",
                    "effective_date": "2026-01-06",
                    "record_date": "2026-01-05",
                    "payment_date": "2026-01-06",
                    "source_url": "https://example.test/late-action",
                    "source_sha256": "b" * 64,
                    "kind": "cash_distribution",
                    "cash_per_unit": 1.0,
                }
            ]
        receipts.append(
            archive_snapshot_payload(
                {
                    "trading_date": session.isoformat(),
                    "captured_at": f"{session.isoformat()}T08:30:00+00:00",
                    "observation_mode": "PROSPECTIVE",
                    "records": [
                        {
                            "symbol": "sh600000",
                            "open": 10.0 if index == 0 else 9.0,
                            "high": 10.0 if index == 0 else 9.0,
                            "low": 10.0 if index == 0 else 9.0,
                            "close": 10.0 if index == 0 else 9.0,
                            "previous_close": 10.0 if index < 2 else 9.0,
                            "volume": 1000,
                            "amount": 20_000_000,
                            "member": True,
                            "st": False,
                            "suspended": False,
                            "exchange": "SSE",
                            "board": "main",
                        }
                    ],
                    "corporate_actions": actions,
                },
                tmp_path,
                provider="fixture",
            )
        )
    early_identity = json.loads(receipts[1].read_text())
    late_identity = json.loads(receipts[2].read_text())
    early = _history(
        tmp_path,
        sessions[1],
        as_of=datetime.fromisoformat(early_identity["captured_at"]),
    )
    late = _history(
        tmp_path,
        sessions[2],
        as_of=datetime.fromisoformat(late_identity["captured_at"]),
    )
    assert early.calc_close.tolist() == [10.0, 9.0]
    assert late.calc_close.tolist() == [10.0, 10.0, 10.0]


def test_acceptance_manifest_stays_rc_and_contains_no_absolute_paths(tmp_path: Path) -> None:
    manifest = build_acceptance_manifest(
        ROOT / "configs/v2/prospective/cn_shadow_v1.yaml",
        tmp_path / "data",
        tmp_path / "artifacts",
        ROOT,
    )
    assert manifest["acceptance_status"] == "OPERATIONS_LOOP_RC"
    assert manifest["missing_acceptance_evidence"] == [
        "GREEN_REMOTE_CI",
        "REAL_T_PLUS_ONE_FILL",
        "REAL_TWO_SIDED_REBALANCE",
    ]
    encoded = json.dumps(manifest)
    assert str(tmp_path.resolve()) not in encoded
    assert "acceptance_id" in manifest
