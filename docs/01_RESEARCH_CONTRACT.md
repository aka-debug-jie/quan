# Research Contract

## Purpose

V1 is a reproducible research and paper-trading platform for a planned
long-only ETF trend and relative-momentum strategy. M0 establishes interfaces
and safeguards only; it does not implement or validate a strategy.

## Time and information boundary

- A signal computed from trading day T closing data may execute no earlier than
  a later exchange-local trading date (T+1 at the earliest).
- Features at time T may use only information that was knowable by T.
- Datasets must preserve point-in-time universe membership. The current ETF
  universe must not be backfilled into historical tests.
- Every run must identify its data snapshot, configuration, code revision when
  available, and random seed.

## Experiment reporting

Every future reported strategy must include CAGR, annualized volatility,
Sharpe ratio, maximum drawdown, turnover, trade count, and a declared benchmark.
Parameter searches must retain all attempted configurations and must separate
selection data from locked evaluation data.

No backtest establishes future profitability. Negative, failed, and abandoned
experiments remain part of the research record.
