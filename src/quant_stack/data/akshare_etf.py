"""AKShare ETF daily-history adapter with offline-testable boundaries."""

from __future__ import annotations

from collections.abc import Callable
from datetime import date
from decimal import Decimal, InvalidOperation
from time import sleep
from typing import Any, cast

import pandas as pd

from quant_stack.data.models import ETFHistoryRequest
from quant_stack.models import DailyBar, PriceBasis
from quant_stack.validation import reject_duplicate_bars

ADAPTER_VERSION = "1.0.0"
REQUIRED_COLUMNS = ("日期", "开盘", "收盘", "最高", "最低", "成交量")
Fetcher = Callable[[ETFHistoryRequest], pd.DataFrame]
Sleep = Callable[[float], None]


class DataFetchError(RuntimeError):
    """Raised after an external provider request cannot be completed."""


class ProviderSchemaError(ValueError):
    """Raised when an AKShare provider export violates the documented daily schema."""


class NormalizationError(ValueError):
    """Raised when a provider row cannot become a valid internal daily bar."""


class AKShareETFAdapter:
    """Fetch raw and front-adjusted ETF daily exports without leaking provider details."""

    def __init__(
        self,
        fetcher: Fetcher | None = None,
        *,
        max_attempts: int = 3,
        retry_delay_seconds: float = 1.0,
        sleep_fn: Sleep = sleep,
    ) -> None:
        if max_attempts < 1:
            raise ValueError("max_attempts must be at least one")
        if retry_delay_seconds < 0:
            raise ValueError("retry_delay_seconds must not be negative")
        self._fetcher = fetcher or _fetch_from_akshare
        self._max_attempts = max_attempts
        self._retry_delay_seconds = retry_delay_seconds
        self._sleep = sleep_fn

    def fetch(self, request: ETFHistoryRequest) -> pd.DataFrame:
        """Fetch and schema-check one provider export, retrying transient failures only."""
        last_error: Exception | None = None
        for attempt in range(1, self._max_attempts + 1):
            try:
                frame = self._fetcher(request)
                validate_provider_frame(frame)
                return frame
            except ProviderSchemaError:
                raise
            except Exception as error:
                last_error = error
                if attempt < self._max_attempts:
                    self._sleep(self._retry_delay_seconds)
        raise DataFetchError(
            "AKShare ETF request failed after "
            f"{self._max_attempts} attempts: {request.instrument.symbol} "
            f"{request.price_basis.value} {request.start_date.isoformat()}.."
            f"{request.as_of_date.isoformat()}"
        ) from last_error


def _fetch_from_akshare(request: ETFHistoryRequest) -> pd.DataFrame:
    """Call AKShare lazily so offline tests never import or contact the provider."""
    try:
        import akshare as ak  # type: ignore[import-untyped]
    except ImportError as error:
        raise DataFetchError("akshare is required for network ETF ingestion") from error
    adjust = "" if request.price_basis is PriceBasis.RAW else request.price_basis.value
    return cast(
        pd.DataFrame,
        ak.fund_etf_hist_em(
            symbol=request.instrument.symbol,
            period=request.period,
            start_date=request.start_date.strftime("%Y%m%d"),
            end_date=request.as_of_date.strftime("%Y%m%d"),
            adjust=adjust,
        ),
    )


def validate_provider_frame(frame: pd.DataFrame) -> None:
    """Validate raw provider shape before persisting or normalizing its contents."""
    if not isinstance(frame, pd.DataFrame):
        raise ProviderSchemaError("AKShare response must be a pandas DataFrame")
    missing = [column for column in REQUIRED_COLUMNS if column not in frame.columns]
    if missing:
        raise ProviderSchemaError(
            f"AKShare response is missing required columns: {', '.join(missing)}"
        )
    if frame.empty:
        raise ProviderSchemaError("AKShare response contains no daily bars")


def provider_export_bytes(frame: pd.DataFrame) -> bytes:
    """Serialize provider columns in stable CSV form; this is not claimed as raw HTTP bytes."""
    validate_provider_frame(frame)
    return frame.to_csv(index=False, lineterminator="\n").encode("utf-8")


def normalize_daily_bars(request: ETFHistoryRequest, frame: pd.DataFrame) -> list[DailyBar]:
    """Map an AKShare daily export to strict internal bars inside the requested interval."""
    validate_provider_frame(frame)
    bars: list[DailyBar] = []
    for row in frame.loc[:, REQUIRED_COLUMNS].to_dict(orient="records"):
        trading_date = _parse_date(row["日期"])
        if trading_date < request.start_date or trading_date > request.as_of_date:
            raise NormalizationError(
                f"provider returned date outside requested interval: {trading_date.isoformat()}"
            )
        try:
            bars.append(
                DailyBar(
                    symbol=request.instrument.symbol,
                    exchange=request.instrument.exchange,
                    price_basis=request.price_basis,
                    trading_date=trading_date,
                    open=_parse_decimal(row["开盘"], "开盘"),
                    high=_parse_decimal(row["最高"], "最高"),
                    low=_parse_decimal(row["最低"], "最低"),
                    close=_parse_decimal(row["收盘"], "收盘"),
                    volume=_parse_decimal(row["成交量"], "成交量"),
                )
            )
        except ValueError as error:
            raise NormalizationError(
                f"invalid provider row for {trading_date.isoformat()}"
            ) from error
    reject_duplicate_bars(bars)
    return sorted(bars, key=lambda bar: bar.trading_date)


def _parse_date(value: Any) -> date:
    """Convert a provider date cell to an exchange-local date."""
    if pd.isna(value):
        raise NormalizationError("日期 must not be empty")
    try:
        return pd.Timestamp(value).date()
    except (TypeError, ValueError) as error:
        raise NormalizationError(f"日期 is not parseable: {value!r}") from error


def _parse_decimal(value: Any, column: str) -> Decimal:
    """Convert one provider numeric cell without retaining binary floating-point semantics."""
    if pd.isna(value):
        raise NormalizationError(f"{column} must not be empty")
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError) as error:
        raise NormalizationError(f"{column} is not numeric: {value!r}") from error
