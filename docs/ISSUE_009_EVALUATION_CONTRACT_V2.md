# Issue 009 Evaluation Contract V2

This supplement was frozen before any locked-test return, feature, signal, or
performance result was calculated. V1 remains preserved as an incomplete
contract and is not an executable locked-test protocol.

## Data and execution

- Features and portfolio return accounting use the D0-qualified PIT causal-adjusted series.
- Every simulated fill is audited at the corresponding immutable raw open.
- Trade quantity equals executed notional divided by raw open; commissions,
  minimum commission, spread, and slippage use the frozen Issue 007 cost model.
- The adjusted price is never recorded as a fill price. Raw and causal panels
  must have identical symbols and trading dates.
- Signals are formed after a valid month-end close and execute at T+1 open.
  The delay stress executes at T+2 open.

This is a fractional-notional research simulation. Corporate-action total
returns are represented by the PIT causal-adjusted accounting series; it does
not claim to reproduce broker custody cash timing. Issue 010 will define the
separate paper ledger and custody accounting contract.

## Frozen periods

The selection period ends on 2023-12-29. Six rolling three-year/one-year OOS
folds are frozen:

1. 2015-01-05--2017-12-29 train; 2018-01-02--2018-12-28 OOS.
2. 2016-01-04--2018-12-28 train; 2019-01-02--2019-12-31 OOS.
3. 2017-01-03--2019-12-31 train; 2020-01-02--2020-12-31 OOS.
4. 2018-01-02--2020-12-31 train; 2021-01-04--2021-12-31 OOS.
5. 2019-01-02--2021-12-31 train; 2022-01-04--2022-12-30 OOS.
6. 2020-01-02--2022-12-30 train; 2023-01-03--2023-12-29 OOS.

The locked test is 2024-01-02--2026-09-09 inclusive. Start sensitivity removes
the first 21 locked sessions; end sensitivity removes the last 21 locked
sessions. These variants do not replace the primary result.

The last locked signal date is 2026-08-31. Sessions from 2026-09-01 through
2026-09-09 are mark-to-market observations only because September is incomplete.

## Frozen configurations

The primary strategy is the existing frozen strategy: 200-session trend,
12-month momentum rank, 60-session inverse-volatility weight, and two selected
positions. The preregistered neighborhood runs every combination of momentum
window 3/6/12 months and selection count 1/2; the primary remains 12 months and
two positions. No diagnostic ablation is added because none was unambiguously
preregistered.

The V2 strategy and benchmark configuration files preserve those formulas and
only update their references to the V2 benchmark and raw-audited execution contract.

Required runs are primary T+1/base cost, 2x cost, T+2, all five non-primary
parameter neighbors, start-trimmed, end-trimmed, and the same-universe monthly
equal-weight benchmark. Every run and every selection-period OOS fold is retained.

Every OOS and locked window begins in cash. Its first eligible signal is the
first completed natural month-end inside that window; training-period holdings
or targets are not carried across the evaluation boundary.

## Classification

The existing nine-condition classification remains authoritative. The two
previously qualitative conditions are frozen as follows:

- Parameter neighborhood is not a single-point peak only when the median of
  the five neighbor locked-test excess CAGRs is non-negative and at least three
  of five are non-negative.
- Performance is not driven by isolated observations only when the primary has
  at least 12 rebalances and the three largest positive daily active returns
  contribute less than 50% of total positive daily active return.

Any precommit mismatch, result-dependent rerun, altered frozen input, leakage,
or failure to retain an executed configuration is `INVALID_RESEARCH_RESULT`.
Otherwise the outcome is `ROBUST_OUTPERFORMANCE_OBSERVED` only when all nine
conditions pass; a valid negative result is `NO_EVIDENCE_OF_EDGE`.
