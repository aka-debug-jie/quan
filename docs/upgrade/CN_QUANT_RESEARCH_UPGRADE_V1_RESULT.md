# CN Quant Research Upgrade V1 result

## Status

- `IMPLEMENTATION_STATUS=COMPLETE_REAL_DATA_RESEARCH_PATH`
- `HISTORICAL_RUN_STATUS=51_REGISTERED_19_VALID_32_NOT_EVALUABLE`
- `DATA_USE_LEVEL=RQALPHA_SINGLE_SOURCE_NONCOMMERCIAL_PRIVATE_RESEARCH_ONLY`
- `RESEARCH_VALIDITY=MIXED_VALID_AND_EXPLICIT_NOT_EVALUABLE`
- `ECONOMIC_OUTCOME=NO_PROMOTABLE_CANDIDATE_MATCHED_BENCHMARKS_NOT_EVALUABLE`
- `PROSPECTIVE_ISOLATION_STATUS=UNCHANGED_ACTIVE_RC02`

This was a fully touched retrospective development study, not a PIT result or
fresh holdout. It did not read CSI500, buy data, add a broker, modify the
prospective account, or deploy a strategy.

## Measurement and accounting audit

The missing-label defect was reproduced and corrected by fixing group members
at T before joining future returns. For the 20-session label, 77 dates had at
least one missing future label; the old 0.8353% Top20-minus-Bottom20 mean became
0.8337%. The aggregate change was small, but the old Bottom group membership
was not semantically valid on affected dates.

The audit also replaced the old whole-period notional/mean-NAV turnover with
daily notional/preceding-close-NAV turnover, while retaining the old metric for
comparison. Costs are split into proportional commission, minimum-commission
uplift, spread, slippage, stamp tax and transfer fee. Spread and slippage enter
the fill price and are not debited from NAV a second time.

Dividend ownership is captured at the record close, recognized as a receivable
on the ex-date, and converted to cash on the payment date. This removes the old
one-day cum-price/receivable double count. Calendar-year returns now include the
first held return across each year boundary.

B00 and A04 both passed a second full-period economic reference that starts
from frozen order intents and independently recomputes fills, costs, cash,
positions, receivables and every daily NAV. This reference does not validate
signal generation or independently parse the vendor corporate-action files.

## Corrected real-cost results

| Strategy | Total return | CAGR | Sharpe | Max DD | Two-sided turnover | Direct costs |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| B00 liquidity Top20 D20 | -47.37% | -5.87% | -0.080 | -74.38% | 55.81 | CNY 63,661 |
| A04 AF7 Top20 D20 | -52.34% | -6.75% | -0.105 | -79.98% | 232.73 | CNY 352,121 |
| AF7 Top50 D20 | -43.36% | -5.22% | -0.074 | -80.03% | 197.63 | CNY 305,622 |
| AF7 Top50 actual-holding buffer/band | -30.06% | -3.32% | 0.002 | -75.43% | 169.22 | CNY 278,760 |
| A01 AF7 Top20 daily | -99.27% | -37.09% | -2.032 | -99.57% | 1,409.79 | CNY 1,076,983 |
| A02R daily actual-holding rank-40 buffer | -98.97% | -35.04% | -1.726 | -99.45% | 1,300.28 | CNY 956,607 |
| A05R D20 actual-holding rank-40 buffer | -58.64% | -7.99% | -0.160 | -83.24% | 214.75 | CNY 304,393 |

The old A01 turnover value 2,904 and the corrected 1,409.79 are different
definitions, not contradictory executions. The latter is the sum of daily
two-sided fill notional divided by the preceding close NAV; its one-way/half
convention is 704.90.

Actual-holding buffers did not rescue the old configurations. A05R lost 1.58
percentage points more total return than the old target-list-buffer A05. A02R
remained near total loss. Buffering did extend holding periods and reduce
turnover, but the economic result stayed negative.

## Cost and delay counterfactuals

| Strategy | Real CAGR | Double-assumption CAGR | Zero-all-cost CAGR | T+2 CAGR |
| --- | ---: | ---: | ---: | ---: |
| B00 | -5.87% | -7.05% | -4.56% | -5.38% |
| A04 AF7 Top20 | -6.75% | -9.29% | -3.58% | -8.92% |
| AF7 Top50 | -5.22% | -7.72% | -1.14% | -6.89% |
| AF7 Top50 buffer/band | -3.32% | -6.02% | -0.32% | -4.75% |

Zero-cost runs recomputed target quantities, cash and fills. Even with all six
explicit costs set to zero, every evaluable AF7 portfolio remained negative.
Costs materially worsened the outcome, but they were not the only cause.

## Signal-source decomposition

Twenty-session forward open returns show that AF7 is primarily an avoidance
signal rather than a winner-selection signal.

| Signal | Top minus pool | Pool minus Bottom | Top minus Bottom | 20d rank autocorrelation | Key exposure |
| --- | ---: | ---: | ---: | ---: | --- |
| AF7 | -0.031% | 0.865% | 0.834% | 0.031 | vol corr -0.165 |
| AF7 residual | -0.357% | 0.510% | 0.153% | 0.008 | beta/vol/liquidity neutral by construction |
| Conditional reversal | 0.111% | 0.249% | 0.360% | -0.017 | weak positive vol/beta exposure |
| Downside-risk filter | 0.781% | 1.657% | 2.439% | 0.901 | vol corr -0.908; beta corr -0.604 |
| 60-to-5 momentum | -1.727% | -0.286% | -2.014% | 0.568 | vol corr 0.423 |
| Robust trend | -0.003% | 0.447% | 0.444% | 0.674 | beta corr -0.417; vol corr -0.351 |

The original AF7 Top group did not beat the pool at the 20-session horizon;
almost all of its spread came from a very weak Bottom group. Residualization
reduced Top-minus-Bottom from 0.834% to 0.153%, showing substantial overlap
with beta, volatility and liquidity exposures without proving the raw signal
spurious. The frozen momentum direction failed. The downside-risk signal was
large but mostly a low-volatility/low-beta exposure, not demonstrated stock
selection alpha. Conditional reversal was the cleanest positive directional
diagnostic, but its executable portfolio was not evaluable.

## Data failures and candidate decisions

The broader executable benchmarks failed closed rather than receiving invented
corporate-action treatment:

- B50: unexplained factor event for `sh601012` on 2019-04-17;
- B100: unexplained factor event for `sz000686` on 2016-04-15.

Other real-cost candidate blockers were `sh600832` missing held valuation on
2015-05-20, and unexplained events for `sz002673` on 2017-04-11 and `sz002017`
on 2019-02-28. Across the 51 registered runs, 19 completed with valid economic
paths and 32 were explicitly not evaluable. No post-result override was added.

Because both preregistered concentration-matched benchmarks were not evaluable,
all eight formal candidate outcomes are `NOT_EVALUABLE`; no capital-scale run
was triggered and no candidate was retained for prospective deployment. This
does not convert the invalid comparisons into `NO_HISTORICAL_EDGE`.

Within the valid subset, the strongest implementation was the AF7 Top50
actual-holding buffer/band. It reduced costs and losses, but still had negative
real, doubled-friction, T+2 and zero-cost CAGR and an approximately 75% maximum
drawdown. It is therefore not a credible promotion candidate even before the
matched-benchmark evidence gap is considered.

## Revisions, failed attempts and boundaries

Nineteen pre-fix run artifacts under protocol hash `6c0b859c...` are retained
as `INVALID_ENGINEERING` evidence. They exposed an ordinary-lot error in
gradual sells, incomplete cache identity, a misplaced reference gate and an
unexplained corporate-action abort. The corrected protocol hash is
`6d205ada...`; its 51 runs are the only runs used above.

The correction improved B00 total return by 3.48 percentage points and A04 by
2.00 points, mainly through corrected dividend/NAV timing and the resulting
order-sizing path. It did not turn either strategy profitable and does not
rewrite the previous V3 conclusion.

No PIT industry, historical shares outstanding or market capitalization data
were available. Amount is reported only as a liquidity proxy. All dates from
2015–2025 were already touched by the project, so no fold is called an untouched
holdout. Block-bootstrap promotion statistics were not interpretable for the
candidate family because the matched benchmarks failed; invalid rows were kept
with p=1 rather than silently dropping dates.

## Validation and isolation

The final implementation used isolated Python 3.11.15 with h5py 3.15.1,
pandas 3.0.5 and pyarrow 23.0.1. Ruff passed, format check passed, strict mypy
passed on 143 source files, and all 530 offline tests passed. Branch-aware total
coverage was 64%.

The live worktree remained clean at `prospective/cn-shadow-v1@68011e8`; the
prospective timer remained active and its latest service result was success
with exit status zero. Service and timer unit hashes remained
`813505ed...e1c1b39` and `3b6a5c76...7b7754`.

This research round stops here. It does not open CSI500, expand the factor
search, buy data, modify the prospective account, or deploy a new strategy.
