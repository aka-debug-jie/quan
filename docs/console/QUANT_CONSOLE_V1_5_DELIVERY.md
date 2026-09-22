# Quant Console V1.5 delivery report

## Result

V1.5 completes the local read-only core journey on approved real artifacts. The UI can
open a pinned snapshot, filter and sort the full experiment registry, inspect detail and
series, validate comparisons, trace evidence, inspect signal/prospective/health state and
export approved aggregates. It cannot run research, alter paper accounts or send orders.

## Real-data parity

The acceptance read model contains 61 displayed runs across Historical V3 and Quant Upgrade
V1. The upgrade study remains 51 registered, 19 valid, 32 `NOT_EVALUABLE`, zero retained
candidates and 19 excluded legacy engineering artifacts. Candidate
`AF7_TOP50_D20_EQ__REAL_T1_1M` retains absolute CAGR -0.05218754030574968 while its matched
benchmark state and economic outcome remain independently `NOT_EVALUABLE`.

Prospective data is read only from published JSON. Engineering warm-start and
`fully_prospective_v1` accounts stay separate; an unstarted formal account is displayed as
unstarted rather than zero. The source data-use level remains private non-commercial
research only.

## Performance

| Measurement | V1 | V1.5 |
|---|---:|---:|
| Current snapshot response median | 41.47 ms | 1.55 ms |
| Overview median | 36.97 ms | 3.00 ms |
| Experiment list median | 43.85 ms | 11.26 ms |
| Prospective median | 37.43 ms | 3.25 ms |
| Health median | 37.80 ms | 3.20 ms |
| Initial JavaScript | 646,838 bytes | 276,166 bytes |

V1.5 list responses are larger because every metric now carries explicit unit, validity and
provenance. Detail and 77,546 NAV points are no longer embedded in the list. ECharts and
AG Grid are lazy route chunks. A 10,000-row service contract test passed in under one second
on the acceptance host.

## Validation summary

- Backend strict ruff/mypy and 11 tests pass with 82.44% branch coverage.
- Frontend lint, typecheck, three unit tests and production build pass.
- Synthetic Playwright: six desktop/mobile tests pass; real-only cases are skipped.
- Real Playwright: two desktop/mobile journeys pass; synthetic-only cases are skipped.
- Axe reports no critical or serious issue on the overview in both viewports.
- npm audit and pip-audit report no known third-party vulnerabilities; the local
  `quant-console` package is expectedly not present on PyPI.
- OpenAPI and generated TypeScript contract drift check passes.

## Boundaries

`STRATEGY_PROMOTION=NOT_AUTHORIZED`, `LIVE_TRADING=FORBIDDEN`, `CSI500=NOT_READ`.
V1 and prospective deployments remain separate and unchanged. Optional component decisions
are recorded in `QUANT_CONSOLE_V1_5_DECISIONS.md`.

