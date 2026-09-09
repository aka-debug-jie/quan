# Delivery Progress

## Repository baseline

- Baseline branch: `main`.
- Baseline commit: pending local Git author identity configuration.
- Remote repository: none configured.
- Git-managed scope excludes `data/`, `artifacts/`, credentials, caches, and
  local environments.

## Issue ledger

| Issue | Branch | Commit | Status | Acceptance evidence | Promotion state |
| --- | --- | --- | --- | --- | --- |
| 001 | pending baseline | pending | Implemented in current baseline | Offline adapter tests; Ruff, mypy, pytest pass | Held by 001-003 shared data gate |
| 002 | pending baseline | pending | Implemented in current baseline | Immutable raw/Parquet/manifest tests pass | Held by 001-003 shared data gate |
| 003 | pending baseline | pending | Implemented in current baseline | Calendar and evidence tests pass | Held: `159919` raw/qfq coverage is incomplete |
| 004 | not created | — | Not started | — | Forbidden before 001-003 gate passes |
| 005 | not created | — | Not started | — | Forbidden before 001-003 gate passes |
| 006 | not created | — | Not started | — | Forbidden before 001-003 gate passes |
| 007 | not created | — | Not started | — | Forbidden before 001-003 gate passes |
| 008 | not created | — | Not started | — | Forbidden before 001-003 gate passes |
| 009 | not created | — | Not started | — | Forbidden before 004-008 gate passes |
| 010 | not created | — | Not started | — | Forbidden before 004-008 gate passes |
| 011 | not created | — | Not started | — | Forbidden before 004-008 gate passes |
| 012 | not created | — | Not started | — | Forbidden before 009 gate passes |

## Current acceptance commands

```bash
uv run ruff check .
uv run ruff format --check .
uv run mypy src
uv run pytest --cov=quant_stack
```

Current result: all checks pass; `50 passed`; coverage is 83%.

## Data-gate evidence

- `510300` raw/qfq: complete, 2,841 bars each.
- `510500` raw/qfq: complete, 2,839 bars each; 2015-04-13 and 2015-04-14
  are documented non-trading events with an archived and hash-verified official
  source.
- `159919` raw/qfq: no bars acquired. The configured AKShare Eastmoney history
  endpoint currently disconnects before returning data, including direct
  requests. This is an external provider availability condition, not a data
  exception and not permission to synthesize or waive bars.

No strategy, feature, portfolio, backtest, Paper Broker, report, or systemd
implementation may begin until `159919` obtains complete raw/qfq coverage with
zero unexplained `expected_session_missing` dates.
