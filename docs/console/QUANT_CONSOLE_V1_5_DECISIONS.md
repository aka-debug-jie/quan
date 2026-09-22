# Quant Console V1.5 component and deferral decisions

## Adopted

| Responsibility | Choice | Version / license | Reason |
|---|---|---|---|
| Requests and cache | TanStack Query | 5.103.2 / MIT | Snapshot-keyed cache, cancellation and bounded retry |
| Experiment grid | AG Grid Community | 36.2.0 / MIT | Accessible mature grid without Enterprise modules |
| API contract | OpenAPI TypeScript + openapi-fetch | 7.13.0 + 0.17.0 / MIT | Generated client checked for drift |
| UI behavior | Radix primitives | pinned lock / MIT | Dialog, tabs, tooltip and selection accessibility without Tailwind migration |
| Charts | Apache ECharts | 6.1.0 / Apache-2.0 | Existing semantics retained; tree-shaken and route-lazy |
| Browser audit | Playwright + axe | 1.63.0 + 4.13.0 / Apache-2.0, MPL-2.0 | Desktop/mobile journeys and serious accessibility checks |
| Read model | PyArrow Parquet + JSON | 25.0.1 / Apache-2.0 | Rebuildable ledger and lazy series without another query engine |

React 18.3.1 and Node 20.19.5 remain in place. Router, Vite, Vitest, Playwright and ECharts
were upgraded because the V1 lock reported 11 known vulnerabilities. The V1.5 npm audit
reported zero known vulnerabilities at acceptance time.

## Implemented P1

- Versioned column layout, compact grid, keyboard-accessible dialogs and URL restoration.
- Route-level code splitting and tree-shaken ECharts imports.
- Structured request logs with request ID, route, status and elapsed time.
- Snapshot age/identity, source integrity, last reload and fixed system observation display.
- Real and 10,000-row synthetic performance checks.

## Deferred or not selected

| Feature | Status | Evidence and current substitute | Restart condition |
|---|---|---|---|
| DuckDB | NOT_SELECTED | Real registry is 61 rows; cached V1.5 list median is about 11 ms and the 10,000-row contract test completes below one second. Parquet ledger plus memory cache is simpler. | Re-evaluate if aggregate rows exceed 10,000 or measured queries become material. |
| Perspective | DEFERRED | AG Grid, predefined signal tables and safe filtered export cover current exploration without ambiguous aggregation or WASM/CSP cost. | A concrete approved aggregation workflow that cannot be expressed by current views. |
| Lightweight Charts | NOT_SELECTED | Tree-shaken ECharts supplies linked NAV/drawdown zoom and tooltip. A second renderer would duplicate responsibility. | Measured ECharts interaction failure on materially larger series. |
| Prometheus/Grafana | DEFERRED | Structured logs, runtime status and request timing provide local observation without opening a service. | User supplies an existing authorized monitoring target. |
| OpenTelemetry and MLflow | NOT_SELECTED | Single local service and frozen research artifacts do not justify new tracing or an alternate fact store. | Multi-service deployment or separately approved experiment tracking contract. |

These items do not block local release and have no hidden routes, disabled buttons or loaded
half-implemented dependencies.

