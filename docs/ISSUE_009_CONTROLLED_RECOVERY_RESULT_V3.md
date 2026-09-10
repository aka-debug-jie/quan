# Issue 009 Controlled Recovery Result V3

Execution status: `PASS`

Issue gate status: `PASS_CONTROLLED_RECOVERY`

Frozen V2-rule outcome: `NO_EVIDENCE_OF_EDGE`

Evidence scope: `CONTROLLED_RECOVERY_RESEARCH`

Holdout status: `NOT_FRESH_PREVIOUSLY_ACCESSED`

Fresh holdout status: `NOT_AVAILABLE`

Live trading authorization: `FORBIDDEN`

## Interpretation

The controlled recomputation executed the unchanged V2 strategy definition and
classification rule successfully. It does not support a claim of strategy edge.
Engineering/data/reproduction acceptance passed, while the quantitative outcome
is a valid negative result. This must not be described as fresh or independent
holdout confirmation, and it does not authorize real orders or result-dependent
parameter changes.

The historical V2 attempt remains `INVALID_RESEARCH_RESULT`. V3 is a separately
authorized controlled recomputation and does not relabel, replace, or delete it.

## Frozen identity

- Runner/code commit: `d865221bfeccaab18f1a32bd61906d8919f14b12`.
- Authorization commit: `cc98d5f`.
- Authorization/precommit ID: `f44f878b37a77d9a39481face4b603e6fb6e4ef0ad8ea492650039d865a99d38`.
- Authorization file SHA-256: `315fcac289c37427d3d379645a7dd8f44e40aa2e1cc3aa7f2f28181d9e3a0b10`.
- Data snapshot ID: `6f33e58c7681a3444d05933d7605672a22940ca5a5039b748d962c419fea4750`.
- V3 contract SHA-256: `6db32327ba46f2ae6271e760d786e762a9e4957905574bb40725f3f7b00198e7`.
- V3 experiment SHA-256: `55e9c3610cd1c8d7988a1c513ad0224070841a59c588d4690969b714845282fb`.
- V2 predecessor precommit ID: `d1c3c371864885134f4a733cebdc09b0fedcd2ca69ad7a8a9c1898c4374fe7c6`.
- V2 attempt SHA-256: `ee0a73f596b7dfc79892c919526f1fa5845c3e40325726d6804c35dc4af1195e`.
- V2 failure SHA-256: `f363c065c07ed96e44b5136326c9b6773d6e5114d2ca5c4092af1ba3734a7820`.

The two V2 receipt hashes were rechecked after V3 execution and are unchanged.

## Complete execution and reproduction evidence

Artifact root:
`artifacts/issue009/locked_runs/f44f878b37a77d9a39481face4b603e6fb6e4ef0ad8ea492650039d865a99d38/`.

- Both fresh Python child processes exited zero; retry count was zero.
- Build A and build B each retained all 16 ordered step files.
- Every corresponding A/B step file is byte-identical.
- Both complete `prepared.json` files are byte-identical.
- Prepared SHA-256: `d85aae7da7aa4b214cd84cdd6a8cfcf49bf4b8f930727b516849ceea62a7a5a6`.
- Reproduction receipt SHA-256: `60b44f78a905b4d2ebf929113fc725cb6a446772d40e57919b9e59542b6445f4`.
- Publication anchor SHA-256: `8ec32744e2db4b39ab73abf7e027dbc8150abee5f7a758c5554a4e47890b9a70`.
- Published result file SHA-256: `66bb1eef61e6de0326cab4a9f5f7df47031f2f505867e1bda1f013c6f998216b`.
- Published result ID: `7056be187280cee637e7ee39fbdebe55ff772df29f209892095f015333800719`.
- All 16 referenced experiment registry records exist.
- No V3 failure receipt exists.

The final result was read back through the strict `PublishedResearchResult`
schema. The schema independently recalculated the frozen decision flags from
the retained metrics, curves and parameter-neighbour results.

## Controlled interval result

Interval: 2024-01-02 through 2026-09-09; last signal date 2026-08-31.
All figures are net of the frozen commission, minimum commission, spread and
slippage model.

| Metric | Strategy | Monthly equal-weight benchmark |
| --- | ---: | ---: |
| CAGR | -1.0429% | 19.6855% |
| Total return | -2.6719% | 59.0769% |
| Annualized volatility | 15.0578% | 20.3030% |
| Sharpe ratio | 0.0064 | 0.9867 |
| Maximum drawdown | -25.2635% | -15.6826% |
| Sortino ratio | 0.0067 | 1.3576 |
| Calmar ratio | -0.0413 | 1.2552 |
| Turnover | 14.7318 | 1.4144 |
| Transaction costs | 1283.42 | 580.04 |
| Rebalances | 32 | 32 |
| Trades | 68 | 97 |
| Time in market | 78.3742% | 96.6258% |
| Longest drawdown | 397 days | 197 days |

Primary excess CAGR was -20.7284 percentage points; Sharpe difference was
-0.9803 and maximum-drawdown difference was -9.5809 percentage points.

## Walk-forward and stress evidence

The six historical OOS strategy/benchmark total returns were:

| Fold | Strategy | Benchmark | Excess CAGR |
| --- | ---: | ---: | ---: |
| 1 | -8.2785% | -29.6045% | 22.0128% |
| 2 | 11.3919% | 28.5070% | -17.9562% |
| 3 | 18.5261% | 38.6650% | -21.1893% |
| 4 | -4.5638% | 1.0522% | -5.8437% |
| 5 | -2.8685% | -12.9238% | 10.4746% |
| 6 | -10.4491% | -15.0054% | 4.7348% |

Median fold excess total return was -0.5298%; exactly 50% of folds had positive
excess total return. These fail the strict positive-median and greater-than-half
conditions.

| Locked stress | Strategy CAGR | Benchmark CAGR | Excess CAGR |
| --- | ---: | ---: | ---: |
| Doubled costs, T+1 | -1.5795% | 19.4702% | -21.0497% |
| Base costs, T+2 | 1.7297% | 19.4852% | -17.7556% |
| Start trimmed 21 sessions | -1.0775% | 20.4045% | -21.4820% |
| End trimmed 21 sessions | -0.6058% | 21.4388% | -22.0446% |

All five parameter-neighbour excess CAGRs were negative: -22.1912%, -23.0151%,
-19.6564%, -21.3458% and -19.2013%. The neighbourhood condition therefore failed.

Only the isolated-observation condition passed among the nine quantitative
conditions: the three largest positive active-return days represented 9.6676%
of total positive active return, and the primary had 32 rebalances. Research
integrity itself passed. The other eight quantitative conditions failed, giving
the frozen valid-negative outcome `NO_EVIDENCE_OF_EDGE`.

## Quality gate

Before authorization and result access:

- Ruff check: PASS.
- Ruff format check: PASS.
- strict mypy: PASS.
- pytest with coverage: 149 passed.
- Combined statement/branch coverage: 71.54%.
- Full synthetic A/B fresh-process rehearsal: PASS.
- Controlled child, fail-closed parent, receipt-only publication and authorization
  self-hash tests: PASS.

## Non-blocking prospective validation

The separate prospective window remains 2026-10 through 2028-03. Its first
eligible signal is the verified October 2026 natural month-end close, with
execution no earlier than the following trading-session open. Interim observations
are non-decisional; the strategy, universe, benchmark, costs and parameters cannot
change in response to them.

This future validation is not required to start subsequent platform engineering.
It will produce a separate prospective result and cannot retroactively upgrade
V3 into a fresh holdout.

## Final decision

`Issue 009 = PASS_CONTROLLED_RECOVERY`.

`Strategy edge = NOT SUPPORTED by the frozen V2 rule on this controlled interval`.

Issue 010 engineering may start under the repository's paper-only, no-live-order
boundary. The V3 result does not justify capital deployment, parameter tuning or
claims of robust outperformance.
