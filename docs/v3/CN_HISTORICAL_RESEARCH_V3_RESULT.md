# CN Historical Research V3 result

## Status

- `IMPLEMENTATION_STATUS=IMPLEMENTED_REAL_DATA_PATH`
- `HISTORICAL_RUN_STATUS=COMPLETE_REAL_DATA`
- `DATA_USE_LEVEL=RQALPHA_SINGLE_SOURCE_NONCOMMERCIAL_PRIVATE_RESEARCH_ONLY`
- `RESEARCH_VALIDITY=VALID_RETROSPECTIVE_DEVELOPMENT_COMPARISON`
- `ECONOMIC_OUTCOME=NO_HISTORICAL_COST_ADJUSTED_EDGE`
- `PROSPECTIVE_ISOLATION_STATUS=SEPARATE_WORKTREE_ENV_DATA_AND_LEDGER`

This is a completed historical development comparison, not a formal PIT result,
fresh holdout, CSI300 replication, paper promotion, or live-trading approval.

## Real input and execution

The run used 2,674 sessions from 2015-01-05 through 2025-12-31, 10,932,892
normalized common-stock rows, and a causal daily top-300 liquidity universe. The
seven frozen AF-003 factors produced exactly 300 scores per session. Raw opens
and closes drove fills and NAV; adjusted histories drove factors.

All portfolios used CNY 1,000,000, 20 equal-weight names, T+1 raw-open matching,
board lots, sell-before-buy, dated transfer fees and stamp tax, minimum
commission, spread, slippage, suspension and limit-price rejection, dividends,
splits, and code conversions. Evidence-backed rights issues were handled by the
preregistered conservative policy of not subscribing and not crediting synthetic
cash or shares.

The final benchmark ledger contains 2,674 snapshots and 7,469 hash-chained
events. Independent persisted-event replay verified the first fill on
2015-01-06, first two-sided rebalance on 2015-02-03, first entitlement/payment on
2015-01-08/09, first held split on 2015-07-27, final cash, receivables, cumulative
costs, every daily NAV, and ledger head.

## Signal diagnostics

| Label / actual interval | Mean IC | Mean Rank-IC | HAC SE (lag 20) | Positive Rank-IC days | Top20-bottom20 mean |
| --- | ---: | ---: | ---: | ---: | ---: |
| Original close T+1 to close T+2 | 0.0129 | 0.0300 | 0.0027 | 59.3% | 0.097% |
| T+1 open to T+2 open | 0.0145 | 0.0324 | 0.0028 | 60.0% | 0.126% |
| T+1 open to T+6 open | 0.0250 | 0.0385 | 0.0046 | 61.6% | 0.424% |
| T+1 open to T+21 open | 0.0237 | 0.0358 | 0.0057 | 60.9% | 0.835% |

The score therefore retains a modest historical ranking direction. This is not
equivalent to a cost-adjusted portfolio edge.

## Cost-adjusted portfolio comparison

| ID | Rule | Total return | CAGR | Sharpe | Max DD | Turnover | Trades | Direct costs | Cost addback return* |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| B00 | Liquidity Top20, 20-session | -50.85% | -6.48% | -0.107 | -74.81% | 56.6 | 2,094 | CNY 63,805 | -44.47% |
| A01 | AF7 Top20, daily | -99.27% | -37.09% | -2.042 | -99.57% | 2,904.0 | 33,005 | CNY 1,052,064 | 5.94% |
| A02 | A01 with rank-40 buffer | -98.78% | -33.99% | -1.664 | -99.34% | 2,040.1 | 31,461 | CNY 964,595 | -2.32% |
| A03 | AF7 Top20, 5-session | -85.00% | -16.38% | -0.496 | -93.38% | 859.2 | 18,098 | CNY 677,914 | -17.20% |
| A04 | AF7 Top20, 20-session | -54.33% | -7.12% | -0.123 | -80.76% | 232.5 | 4,979 | CNY 339,503 | -20.38% |
| A05 | A04 with rank-40 buffer | -57.06% | -7.66% | -0.142 | -82.49% | 216.7 | 4,740 | CNY 311,055 | -25.96% |

\* Direct cost addback holds executed quantities fixed. It is an attribution,
not a self-financing zero-cost backtest.

A04 was the closest seven-factor configuration to B00, but still had 0.65
percentage points lower CAGR, lower Sharpe, and 5.96 percentage points worse
maximum drawdown. It exceeded B00 in only 45.5% of calendar years. A05 reduced
turnover and direct costs relative to A04 but worsened return, Sharpe, and
drawdown. Buffer neighbors 30/50, doubled friction, and T+2 execution did not
change the negative conclusion.

## Answers to the research questions

1. **Is the original seven-factor score worth continuing?** It has modest,
   persistent historical Rank-IC, so it remains useful as a signal diagnostic.
   It is not supported as a standalone cost-adjusted Top20 strategy.
2. **Did lower turnover add paired value?** It prevented the near-total loss of
   daily and 5-session variants. The 20-session variants were economically much
   better, but neither beat B00. The rank-40 buffer reduced costs without adding
   net return.
3. **What changed with horizon?** Rank-IC and spread were stronger at 5/20-day
   horizons, while slower portfolios behaved more like the broad liquid-stock
   exposure. The improvement is mainly lower churn and market exposure, not a
   demonstrated alpha increment.
4. **What drove the result?** Daily configurations were dominated by turnover
   and costs; A01 accumulated costs exceeding initial capital. Even the A04
   fixed-quantity cost addback remained negative, so signal/selection and market
   losses also matter. Data limitations affect claim strength but do not explain
   the daily turnover failure.
5. **One next experiment:** if research resumes, run one industry/size exposure
   attribution and neutralized portfolio test using the same frozen scores and
   monthly cadence. Do not add factors or models before that diagnostic.

## Boundaries and validation

BaoStock independent cross-checking was attempted twice with a fixed 36-key
sample but produced no response rows before the bounded timeout. No third data
provider was added. Results therefore remain single-vendor, final-revised,
non-commercial historical research.

Local validation used an isolated Python 3.11 runtime: Ruff passed, format check
passed, strict mypy passed on 132 source files, and all 471 offline tests passed.
Branch-aware total coverage was 65%. Real data, ledgers, NAV and symbol-level
artifacts remain ignored; only hashes and aggregate evidence are committed.
GitHub CI run `35624309945` independently passed the full checks, V2 environment,
and new V3 historical environment jobs.

CSI500 was not read. EXQ-001, BT-001, the V2 no-formal-qualification closure,
the prospective timer, prospective data, paper accounts and live-order boundary
remain unchanged. This first round stops here without factor search or strategy
deployment.
