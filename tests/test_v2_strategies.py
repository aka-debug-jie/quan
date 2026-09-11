"""Offline contracts for V2-A/B/C strategy research gates."""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

import pytest

from quant_stack.models import ManifestFile
from quant_stack_v2.dual_momentum import (
    DualMomentumError,
    build_dual_momentum_report,
    reject_execution_use,
)
from quant_stack_v2.fundamentals import (
    FundamentalGateError,
    FundamentalObservation,
    build_factor_ranking_report,
    qualify_fundamentals,
    rank_deterministic_factors,
)
from quant_stack_v2.pit import build_pit_universe
from quant_stack_v2.qlib_import import QlibInstrumentInterval
from quant_stack_v2.residual_alpha import (
    ResidualAlphaError,
    ResidualExample,
    compare_net_increment,
    validate_residual_examples,
    validate_residual_metric_schema,
)
from quant_stack_v2.yahoo_etf import (
    DEFAULT_YAHOO_ETF_SYMBOLS,
    YahooAdjustedClose,
    YahooProviderManifest,
    YahooSnapshotReport,
    YahooSymbolSnapshot,
)


def _snapshot() -> YahooSnapshotReport:
    start = date(2020, 1, 1)
    sessions = tuple(start + timedelta(days=index) for index in range(280))
    snapshots = []
    for order, symbol in enumerate(DEFAULT_YAHOO_ETF_SYMBOLS):
        daily_increment = 0 if symbol == "BIL" else order + 1
        bars = tuple(
            YahooAdjustedClose(
                symbol,
                session,
                Decimal("100") + Decimal(daily_increment * index),
            )
            for index, session in enumerate(sessions)
        )
        manifest = YahooProviderManifest(
            symbol=symbol,
            manifest_id=f"{order:064x}",
            source_url="https://query1.finance.yahoo.com/example",
            canonical_request="fixed",
            request_parameters={},
            adapter_version="test",
            retrieved_at=datetime(2026, 1, 1, tzinfo=UTC),
            http_metadata={":status": "200"},
            raw_file=ManifestFile(relative_path="raw", sha256="a" * 64, size_bytes=1),
            normalized_file=ManifestFile(relative_path="normalized", sha256="b" * 64, size_bytes=1),
            row_count=len(bars),
            event_count=0,
            first_trading_date=sessions[0],
            last_trading_date=sessions[-1],
            raw_sha256="c" * 64,
        )
        snapshots.append(YahooSymbolSnapshot(manifest, bars, (), ()))
    return YahooSnapshotReport(tuple(snapshots), sessions, ())


def test_dual_momentum_is_monthly_research_signal_and_rejects_execution() -> None:
    report = build_dual_momentum_report(
        _snapshot(), dataset_report_sha256="a" * 64, config_sha256="b" * 64
    )
    assert report.status == "RESEARCH_SIGNAL_ONLY"
    assert report.signals
    assert all(signal.selected_symbols == ("DBC", "GLD", "IEF") for signal in report.signals)
    with pytest.raises(DualMomentumError, match="research-only"):
        reject_execution_use(report, "paper_broker")


def test_dual_momentum_rejects_snapshot_anomalies() -> None:
    snapshot = _snapshot()
    from quant_stack_v2.yahoo_etf import YahooDataAnomaly

    bad = YahooSnapshotReport(
        snapshot.symbol_snapshots,
        snapshot.common_trading_dates,
        (YahooDataAnomaly("SPY", "missing_adjusted_close", "fixture"),),
    )
    with pytest.raises(DualMomentumError, match="anomalies"):
        build_dual_momentum_report(bad, dataset_report_sha256="a" * 64, config_sha256="b" * 64)


def _fundamental(
    symbol: str, field: str, value: str, industry: str = "tech"
) -> FundamentalObservation:
    return FundamentalObservation(
        symbol=symbol,
        field=field,
        value=Decimal(value),
        industry=industry,
        effective_date=date(2020, 1, 1),
        published_at=date(2020, 1, 2),
        available_from=date(2020, 1, 2),
        raw_sha256="a" * 64,
    )


def test_fundamental_qualification_and_industry_standardized_ranking() -> None:
    observations = tuple(
        _fundamental(symbol, field, value)
        for symbol, values in {"a": ("1", "2", "3"), "b": ("2", "3", "4")}.items()
        for field, value in zip(
            ("book_to_price", "return_on_equity", "momentum_12_1"), values, strict=True
        )
    )
    qualification = qualify_fundamentals(
        observations,
        source_id="fixture",
        source_snapshot_sha256="b" * 64,
        pit_universe_sha256="c" * 64,
    )
    universe = build_pit_universe(
        "csi300",
        (
            QlibInstrumentInterval("a", date(2020, 1, 1), date(2020, 1, 31)),
            QlibInstrumentInterval("b", date(2020, 1, 1), date(2020, 1, 31)),
        ),
    )
    ranked = rank_deterministic_factors(
        session=date(2020, 1, 3),
        universe=universe,
        qualification=qualification,
        observations=observations,
    )
    assert qualification.status == "QUALIFIED"
    assert [item.symbol for item in ranked] == ["b", "a"]
    ranking_report = build_factor_ranking_report(
        session=date(2020, 1, 3),
        universe=universe,
        pit_universe_sha256="c" * 64,
        qualification=qualification,
        observations=observations,
    )
    assert ranking_report.status == "RESEARCH_RANKING_ONLY"


def test_factor_ranking_rejects_missing_pit_member_input() -> None:
    report = qualify_fundamentals(
        (_fundamental("a", "book_to_price", "1"),),
        source_id="fixture",
        source_snapshot_sha256="b" * 64,
        pit_universe_sha256="c" * 64,
    )
    universe = build_pit_universe(
        "csi300", (QlibInstrumentInterval("a", date(2020, 1, 1), date(2020, 1, 31)),)
    )
    with pytest.raises(FundamentalGateError, match="missing verified"):
        rank_deterministic_factors(
            session=date(2020, 1, 3),
            universe=universe,
            qualification=report,
            observations=(_fundamental("a", "book_to_price", "1"),),
        )


def test_residual_alpha_rejects_leakage_and_requires_cost_matched_increment() -> None:
    valid = ResidualExample(
        "a",
        date(2020, 1, 1),
        date(2020, 1, 1),
        date(2020, 1, 21),
        date(2020, 1, 21),
        date(2020, 1, 2),
        Decimal("0.01"),
        Decimal("0.02"),
    )
    validate_residual_examples((valid,))
    result = compare_net_increment(
        Decimal("0.10"),
        Decimal("0.01"),
        Decimal("0.13"),
        Decimal("0.01"),
        same_universe=True,
        same_delay=True,
        same_cost_model=True,
    )
    assert result.status == "PASS"
    validate_residual_metric_schema(
        {
            "ic": Decimal("0"),
            "rank_ic": Decimal("0"),
            "icir": Decimal("0"),
            "cagr": Decimal("0"),
            "annualized_volatility": Decimal("0"),
            "sharpe_ratio": Decimal("0"),
            "maximum_drawdown": Decimal("0"),
            "turnover": Decimal("0"),
            "trade_count": Decimal("0"),
            "total_transaction_costs": Decimal("0"),
            "benchmark_relative_return": Decimal("0"),
        }
    )
    leaky = ResidualExample(
        "a",
        date(2020, 1, 1),
        date(2020, 1, 2),
        date(2020, 1, 21),
        date(2020, 1, 21),
        date(2020, 1, 2),
        Decimal("0"),
        Decimal("0"),
    )
    with pytest.raises(ResidualAlphaError, match="not available"):
        validate_residual_examples((leaky,))
    with pytest.raises(ResidualAlphaError, match="retain the V2-B"):
        compare_net_increment(
            Decimal("0"),
            Decimal("0"),
            Decimal("0"),
            Decimal("0"),
            same_universe=False,
            same_delay=True,
            same_cost_model=True,
        )
