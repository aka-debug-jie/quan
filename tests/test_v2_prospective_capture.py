"""Offline provider-contract coverage for prospective free data."""

from __future__ import annotations

import json
from datetime import UTC, date, datetime
from pathlib import Path

import pandas as pd

from quant_stack.data.calendar import ExchangeCalendarStore
from quant_stack.models import Exchange
from quant_stack_v2.prospective_capture import (
    LiveQueries,
    _resolve_action_cache,
    capture_live_session,
)
from quant_stack_v2.prospective_runner import run_daily

ROOT = Path(__file__).parents[1]


def test_action_refresh_failure_uses_recent_cache_or_marks_unknown(tmp_path: Path) -> None:
    captured = datetime(2026, 3, 2, 9, 0, tzinfo=UTC)
    actions, unresolved = _resolve_action_cache(
        tmp_path,
        date(2026, 3, 2),
        captured,
        ("sh600000",),
        [],
        [{"symbol": "sh600000", "error": "offline"}],
    )
    assert actions == []
    assert unresolved == {"sh600000"}
    _resolve_action_cache(tmp_path, date(2026, 3, 2), captured, ("sh600000",), [], [])
    actions, unresolved = _resolve_action_cache(
        tmp_path,
        date(2026, 3, 3),
        datetime(2026, 3, 3, 9, 0, tzinfo=UTC),
        ("sh600000",),
        [],
        [{"symbol": "sh600000", "error": "offline"}],
    )
    assert actions == []
    assert unresolved == set()


def test_capture_live_session_normalizes_all_required_sources(tmp_path: Path) -> None:
    members = pd.DataFrame(
        [
            {
                "日期": date(2026, 3, 2),
                "成分券代码": f"{600000 + index:06d}",
                "成分券名称": f"member-{index}",
                "交易所": "上海证券交易所",
            }
            for index in range(300)
        ]
    )

    def history(symbol: str, start: date, end: date) -> pd.DataFrame:
        index = int(symbol[-3:])
        return pd.DataFrame(
            [
                {
                    "date": start,
                    "open": 10 + index / 100,
                    "high": 11 + index / 100,
                    "low": 9 + index / 100,
                    "close": 10 + index / 100,
                    "volume": 1_000_000,
                    "amount": 20_000_000,
                },
                {
                    "date": end,
                    "open": 10.1 + index / 100,
                    "high": 11.1 + index / 100,
                    "low": 9.1 + index / 100,
                    "close": 10.2 + index / 100,
                    "volume": 1_000_100,
                    "amount": 20_100_000,
                },
            ]
        )

    spot = pd.DataFrame(
        [
            {"code": f"sh{600000 + index:06d}", "name": f"member-{index}", "state": ""}
            for index in range(300)
        ]
    )

    def actions(symbol: str) -> pd.DataFrame:
        if symbol != "sh600000":
            return pd.DataFrame(
                columns=[
                    "实施方案公告日期",
                    "送股比例",
                    "转增比例",
                    "派息比例",
                    "股权登记日",
                    "除权日",
                    "派息日",
                ]
            )
        return pd.DataFrame(
            [
                {
                    "实施方案公告日期": date(2026, 2, 20),
                    "送股比例": 0,
                    "转增比例": 0,
                    "派息比例": 2,
                    "股权登记日": date(2026, 2, 27),
                    "除权日": date(2026, 3, 2),
                    "派息日": date(2026, 3, 2),
                }
            ]
        )

    benchmark = pd.DataFrame(
        [
            {
                "date": date(2026, 3, 2),
                "open": 4000,
                "high": 4100,
                "low": 3990,
                "close": 4050,
                "amount": 1_000_000,
            }
        ]
    )
    queries = LiveQueries(lambda: members, history, lambda: spot, actions, lambda: benchmark)
    receipt = capture_live_session(
        tmp_path,
        session=date(2026, 3, 2),
        previous_session=date(2026, 2, 27),
        allow_network=True,
        queries=queries,
        captured_at=datetime(2026, 3, 2, 8, 30, tzinfo=UTC),
    )
    identity = json.loads(receipt.read_text())
    payload = json.loads(Path(identity["snapshot_path"]).read_text())
    assert payload["observation_mode"] == "PROSPECTIVE"
    assert len(payload["records"]) == 300
    assert payload["corporate_actions"][0]["cash_per_unit"] == 0.2
    assert payload["benchmark"]["close"] == 4050


def test_complete_daily_runner_bootstraps_and_reports_offline(tmp_path: Path) -> None:
    calendar = ExchangeCalendarStore(ROOT / "configs/calendars")
    members = pd.DataFrame(
        [
            {
                "日期": date(2026, 3, 2),
                "成分券代码": f"{600000 + index:06d}",
                "成分券名称": f"member-{index}",
                "交易所": "上海证券交易所",
            }
            for index in range(300)
        ]
    )

    def history(symbol: str, start: date, end: date) -> pd.DataFrame:
        index = int(symbol[-3:])
        sessions = calendar.sessions_between(Exchange.SSE, start, end)
        return pd.DataFrame(
            [
                {
                    "date": session,
                    "open": 10 + index / 100 + offset / 1000,
                    "high": 10.3 + index / 100 + offset / 1000,
                    "low": 9.8 + index / 100 + offset / 1000,
                    "close": 10.1 + index / 100 + offset * ((index % 7) + 1) / 1000,
                    "volume": 1_000_000 + index + offset,
                    "amount": 20_000_000 + index,
                }
                for offset, session in enumerate(sessions)
            ]
        )

    spot = pd.DataFrame(
        [
            {"code": f"sh{600000 + index:06d}", "name": f"member-{index}", "state": ""}
            for index in range(300)
        ]
    )
    empty_actions = pd.DataFrame()
    benchmark_sessions = calendar.sessions_between(
        Exchange.SSE, date(2025, 10, 1), date(2026, 3, 2)
    )
    benchmark = pd.DataFrame(
        [
            {
                "date": session,
                "open": 4000 + offset,
                "high": 4010 + offset,
                "low": 3990 + offset,
                "close": 4005 + offset,
                "amount": 1_000_000,
            }
            for offset, session in enumerate(benchmark_sessions)
        ]
    )
    queries = LiveQueries(
        lambda: members,
        history,
        lambda: spot,
        lambda _symbol: empty_actions,
        lambda: benchmark,
    )
    report = run_daily(
        ROOT / "configs/v2/prospective/cn_shadow_v1.yaml",
        tmp_path / "data",
        tmp_path / "artifacts",
        calendar_root=ROOT / "configs/calendars",
        rules_path=ROOT / "configs/v2/prospective/cn_shadow_rules_v1.yaml",
        allow_network=True,
        session=date(2026, 3, 2),
        queries=queries,
        now=datetime(2026, 3, 2, 9, 0, tzinfo=UTC),
    )
    payload = json.loads(report.read_text())
    assert payload["ENGINEERING_STATUS"] == "DAILY_RUN_COMPLETE"
    assert payload["INPUT_STATUS"] == "MIXED_PROSPECTIVE_INPUT"
    assert payload["DATA_CAPTURE_STATUS"] == "COMPLETE"
    assert payload["capture_receipt_policy"] == "FIRST_IMMUTABLE_RECEIPT"
    assert payload["SHADOW_SIGNAL_STATUS"] == "SIGNAL_EMITTED"
    assert payload["PAPER_ACCOUNT_STATUS"] == "RECONCILED_LOCAL_ONLY"
    repeated = run_daily(
        ROOT / "configs/v2/prospective/cn_shadow_v1.yaml",
        tmp_path / "data",
        tmp_path / "artifacts",
        calendar_root=ROOT / "configs/calendars",
        rules_path=ROOT / "configs/v2/prospective/cn_shadow_rules_v1.yaml",
        allow_network=False,
        session=date(2026, 3, 2),
        queries=queries,
        now=datetime(2026, 3, 2, 9, 0, tzinfo=UTC),
    )
    assert repeated == report
