"""VectorBT adapter with an explicit close-signal to next-session execution boundary."""

from __future__ import annotations

import pandas as pd
import vectorbt as vbt  # type: ignore[import-untyped]


def run_t1_backtest(close: pd.Series, close_signal: pd.Series) -> vbt.Portfolio:
    """Run a long-only VectorBT portfolio where a signal on T may enter no earlier than T+1."""
    if not close.index.equals(close_signal.index):
        raise ValueError("close and close_signal must share an identical index")
    entries = close_signal.shift(1, fill_value=False).astype(bool)
    return vbt.Portfolio.from_signals(close, entries=entries, exits=False, direction="longonly")
