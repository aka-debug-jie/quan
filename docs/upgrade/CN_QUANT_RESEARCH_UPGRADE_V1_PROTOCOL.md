# CN Quant Research Upgrade V1 protocol

Status: `PREREGISTERED_BEFORE_PORTFOLIO_RETURNS`.

This is an isolated, fully touched retrospective research comparison. It does
not amend the running prospective system, the V3 historical result, the
CSI500 seal, or the prohibition on live brokerage. The machine-readable
authority is `configs/upgrade/cn_quant_research_upgrade_v1.yaml`.

## Inputs and measurement repairs

The study reuses only the existing content-addressed RQAlpha bundle, normalized
bars, AF7 scores, dated costs, corporate actions and trading rules. Data use is
limited to private, non-commercial research and redistribution is forbidden.

Before comparing strategies, the study fixes T-date Top/Bottom membership,
reports missing-label coverage without replacement, measures daily turnover
against the preceding close NAV, separates five cost components, uses actual
holdings for buffers, recognizes dividend receivables on the ex-date, and
calculates calendar-year returns across year boundaries. Old V3 artifacts are
retained unchanged and all before/after differences are reported.

B00 and A04 must match a second full-period economic reference account that
does not import the primary account, fill or cost functions. An unexplained
difference makes dependent conclusions not evaluable.

## Frozen experiment family

The core registry contains four references/benchmarks and eight candidates,
each under real T+1 costs, doubled non-statutory assumptions, zero explicit
costs, and real-cost T+2 execution. Three legacy/corrected audit runs bring the
fixed count to 51. At most two candidates may receive the two frozen capital
scale checks, giving a hard maximum of 55 runs.

The new mechanisms are exactly 60-to-5-session momentum, liquidity/volatility
conditioned five-session reversal, 60-session downside semivolatility, and the
equal-z robust-trend combination. There is no learned model, parameter grid,
candidate replacement or post-result signal expansion.

All portfolios remain long-only, unlevered, self-financing, board-lot aware,
sell-before-buy, T+1-or-later, and subject to the existing suspension and price
limit rules. Zero-cost analysis recomputes quantities and fills; it is not a
fee addback.

## Primary evidence and stopping rule

Candidates are compared with concentration-matched executable liquidity
benchmarks using net active CAGR, paired daily log returns, Sharpe difference,
drawdown, preceding-NAV turnover, costs, eleven calendar years, doubled
friction and T+2 delay. Paired inference uses shared 21-session date blocks,
10,000 replications, seed 20260922 and Holm correction across eight candidates.

Outcomes are limited to `RETAIN_FOR_PROSPECTIVE_VALIDATION_ONLY`,
`INCONCLUSIVE_HISTORICAL`, `NO_HISTORICAL_EDGE`, or `NOT_EVALUABLE`. Even a
retained candidate receives no deployment permission. The study stops when the
registered budget and report are complete; it does not consume CSI500, buy
data, add a broker, or start another factor search.
