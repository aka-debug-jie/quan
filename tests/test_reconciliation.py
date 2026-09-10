from datetime import date
from decimal import Decimal

from quant_stack.data.models import ProviderId, ProviderSeriesManifest
from quant_stack.data.reconciliation import reconcile_raw_series
from quant_stack.models import DailyBar, Exchange, Instrument, ManifestFile, PriceBasis


def _manifest(
    provider: ProviderId,
    digest: str,
    volume_unit: str = "unspecified",
) -> ProviderSeriesManifest:
    return ProviderSeriesManifest(
        manifest_id=digest,
        provider=provider,
        instrument=Instrument(symbol="159919", exchange=Exchange.SZSE),
        price_basis=PriceBasis.RAW,
        volume_unit=volume_unit,
        source_url="https://example.invalid/source",
        retrieved_at="2024-01-02T00:00:00+00:00",
        request_parameters={},
        http_metadata={},
        parser_version="1",
        normalization_version="1",
        raw_file=ManifestFile(relative_path="raw", sha256="a" * 64, size_bytes=1),
        normalized_file=ManifestFile(relative_path="normalized", sha256="b" * 64, size_bytes=1),
        row_count=1,
        first_trading_date=date(2024, 1, 2),
        last_trading_date=date(2024, 1, 2),
    )


def _bar(volume: str = "1") -> DailyBar:
    return DailyBar(
        symbol="159919",
        exchange=Exchange.SZSE,
        price_basis=PriceBasis.RAW,
        trading_date=date(2024, 1, 2),
        open=Decimal("10"),
        high=Decimal("10"),
        low=Decimal("10"),
        close=Decimal("10"),
        volume=Decimal(volume),
    )


def test_missing_independent_cross_check_is_a_blocked_report() -> None:
    report = reconcile_raw_series(
        _manifest(ProviderId.SZSE_OFFICIAL, "c" * 64), [_bar()], None, None
    )

    assert report.status == "blocked"
    assert report.overlap_sessions == 0
    assert report.mismatched_sessions == 0


def test_reconciliation_does_not_merge_series_and_detects_disagreement() -> None:
    report = reconcile_raw_series(
        _manifest(ProviderId.SZSE_OFFICIAL, "c" * 64),
        [_bar()],
        _manifest(ProviderId.AKSHARE_EASTMONEY, "d" * 64),
        [_bar("2")],
    )

    assert report.status == "blocked"
    assert report.overlap_sessions == 1
    assert report.mismatched_sessions == 1


def test_reconciliation_accepts_explicit_shares_to_lots_volume_conversion() -> None:
    report = reconcile_raw_series(
        _manifest(ProviderId.SINA, "c" * 64, "shares"),
        [_bar("100")],
        _manifest(ProviderId.SZSE_OFFICIAL, "d" * 64, "lots"),
        [_bar("1")],
    )

    assert report.status == "pass"
    assert report.mismatched_sessions == 0
    assert report.source_to_cross_check_volume_multiplier == "0.01"
    assert report.cross_check_volume_tolerance == "0.5"


def test_sina_to_akshare_crosscheck_accounts_for_js_float_volume_precision() -> None:
    report = reconcile_raw_series(
        _manifest(ProviderId.SINA, "c" * 64, "shares"),
        [_bar("10144")],
        _manifest(ProviderId.AKSHARE_EASTMONEY, "d" * 64, "lots"),
        [_bar("100")],
    )
    assert report.status == "pass"
    assert report.cross_check_volume_tolerance == "2"
