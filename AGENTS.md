# Quant Stack Engineering Rules

## Mission

Build a reproducible Linux-first quantitative research and paper-trading
platform. The first planned strategy is a long-only ETF trend and
relative-momentum strategy. This repository must not send live orders.

## Non-negotiable research rules

1. A signal calculated with day T closing data may execute no earlier than T+1.
2. Do not use future information, backfilled leakage, or a current universe as a historical universe.
3. Every backtest must include commissions, minimum commissions, spread, and slippage.
4. Raw downloaded data is immutable and content-addressed.
5. Tests must never depend on live network access.
6. Backtests must be deterministic under a fixed seed and data snapshot.
7. Every reported strategy must include CAGR, volatility, Sharpe ratio, maximum drawdown, turnover, trade count, and a benchmark comparison.
8. Parameter sweeps must retain every attempted configuration, not only winners.
9. No V1, V2, research branch or automation may add or invoke a live brokerage adapter or real-order submission unless a future separately approved contract explicitly authorizes it.
10. Never commit secrets, tokens, cookies, broker credentials, or account identifiers.

## Engineering rules

1. Use Python 3.11 and uv.
2. Use a src layout and strict type annotations.
3. Use pathlib instead of string-built paths.
4. Use UTC internally and store exchange-local trading dates explicitly.
5. Public functions require docstrings and type hints.
6. New behavior requires tests.
7. Run ruff, mypy, pytest, and coverage before declaring a task complete.
8. Do not silently catch exceptions.
9. Network adapters must use retries, timeouts, schema validation, and caching.
10. Keep strategy logic independent from data providers and backtest engines.

## Code review rules

Reject changes that:

- introduce look-ahead bias;
- execute a T-day signal at the T-day close;
- omit transaction costs;
- mutate historical raw data;
- make tests depend on live APIs;
- add broker order submission;
- expose credentials;
- change strategy definitions without updating the research contract.
