# Delivery Progress

## Repository baseline

- Baseline branch: `main`.
- Baseline commit: `53cf6d3187b5c90147f6bfe8b8de259a2bb4f38d`.
- Remote repository: none configured.
- Git-managed scope excludes `data/`, `artifacts/`, credentials, caches, and
  local environments.

## Issue ledger

| Issue | Branch | Commit | Status | Acceptance evidence | Promotion state |
| --- | --- | --- | --- | --- | --- |
| 001 | `issue/001-akshare-etf-adapter` | baseline `53cf6d3` | Implemented in captured baseline | Offline adapter tests; Ruff, mypy, pytest pass | Held by 001-003 shared data gate |
| 002 | `issue/002-provenance-manifests` | baseline `53cf6d3` | Implemented in captured baseline | Immutable raw/Parquet/manifest tests pass | Held by 001-003 shared data gate |
| 003 | `issue/003-calendar-coverage-gate` | baseline `53cf6d3`; gate review `0e9dd5b` | Implemented; real-data acceptance blocked | Calendar, evidence, and coverage tests pass | Held: `159919` raw/qfq coverage is incomplete |
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

## Current branch review

- Branch: `issue/003-calendar-coverage-gate`.
- Reviewed scope: data adapter, immutable source capture, calendar source
  archives, evidence-backed non-trading events, and coverage logic only.
- Review outcome: no live-order, credential, strategy, T+1, cost, or future-data
  behavior was added. `510500`'s two absences require a hash-verified official
  PDF and never synthesize OHLC.
- Remaining external blocker: AKShare's configured Eastmoney historical K-line
  endpoint terminates TLS reads before returning `159919` data. Direct endpoint
  probes exhibit the same failure. No alternate provider has been introduced.

## Provider probe log

- 2026-09-10 Asia/Shanghai: an explicit short-range
  `ak.fund_etf_hist_em(symbol="159919", start_date="20150105",
  end_date="20150130", adjust="")` probe again failed with a remote TLS read
  disconnect. This confirms the block is not caused by multi-year request size.
- No fallback provider, manual CSV import, synthetic bar, or data waiver was
  used after this probe.
