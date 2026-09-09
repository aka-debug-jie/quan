# Issue 009 Evaluation Contract

This contract is frozen before the locked test is run.

## Benchmark and execution

Primary benchmark: `SAME_UNIVERSE_EQUAL_WEIGHT`, using the frozen ETF universe,
monthly equal-weight rebalance, the same causal-adjusted data snapshot, T+1
execution calendar, tradability rules, and full commission, minimum commission,
spread, and slippage model as the strategy. It has no trend, momentum,
inverse-volatility, or tactical-cash rule.

Strategy rebalances after the final valid close of each natural month. Signals
and targets are computed after that close; execution is at the next valid session
open (T+1) plus the frozen cost model. Daily close marks holdings. T+1 failure is
recorded as delayed or rejected, never synthesized. Corporate actions use the
PIT-safe causal-adjusted series.

## Evaluation

Use the pre-registered splits and locked-test boundary without modification.
All returns are net of costs; annualization is 252 trading days and risk-free
rate is zero. Report CAGR, annualized volatility, Sharpe, maximum drawdown,
Sortino, Calmar, total return, turnover, transaction costs, rebalances, time in
market, cash statistics, best/worst calendar year, longest drawdown, and relative
benchmark metrics (excess CAGR, Sharpe and drawdown difference, tracking error,
and positive-excess OOS-fold percentage).

## Robustness and classification

Run base cost, doubled cost, T+2 execution, the frozen parameter neighborhood,
start/end sensitivity, benchmark comparison, and unambiguous pre-registered
ablations. Persist every executed configuration and every OOS fold.

Classify `ROBUST_OUTPERFORMANCE_OBSERVED` only if every condition in the frozen
goal protocol is met; otherwise classify `NO_EVIDENCE_OF_EDGE`. Any leakage,
post-selection, benchmark change, cost change, split change, or locked-test
contamination is `INVALID_RESEARCH_RESULT` and prevents Issue 009 PASS.
