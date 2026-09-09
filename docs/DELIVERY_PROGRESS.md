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
| 003 | `issue/003-159919-szse-recovery` | baseline `53cf6d3`; accepted head pending this update | PASS | Raw/qfq coverage, official evidence ledger, PIT view, factor reconciliation, Ruff, mypy, pytest pass | Issue 004 may be created only by explicit next action |
| 004 | `issue/004-features` | base `eea1e16` | Implemented; acceptance review pending | PIT-safe feature warm-up tests; Ruff, mypy, pytest pass | Do not enter Issue 005 before review and accepted commit |
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

Recovery result: Ruff, formatting, strict mypy, and `60 passed` all pass. The
Issue 003 real-data acceptance gate remains blocked; see
`ISSUE_003_159919_RECOVERY_REPORT.md`.

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

## 159919 secondary-provider recovery

- Branch: `issue/003-159919-szse-recovery`.
- The SZSE official `getHistoryData` endpoint was captured as a separate raw-only
  provider series with HTTP metadata, a raw JSON SHA-256, native Parquet, and a
  provider manifest. It yielded 201 sessions (2025-11-14 through 2026-09-09),
  leaving 2,640 expected sessions missing from the 2015-onward required range.
- The authoritative corporate-action ledger configuration is intentionally
  `incomplete`; the canonical qfq algorithm refuses it. No provider series was
  merged, no OHLC was generated, and no original AKShare evidence was changed.
- Tushare is not installed and no `TUSHARE_TOKEN` is configured, so it was not
  used as a cross-check. The reconciliation outcome is `blocked`, not an empty
  pass. See `ISSUE_003_159919_RECOVERY_REPORT.md` for A–J evidence.
- Subsequent recovery: the independent Sina raw series now has complete calendar
  coverage once the official 2019-01-11 conversion suspension is applied; it was
  cross-checked against all 201 SZSE sessions and published as canonical raw only.
  qfq remains blocked by the incomplete official corporate-action ledger.
- Final Issue 003 recovery disposition: `BLOCKED_EXTERNAL`. SZSE is limited to
  201 sessions under tested pagination and date parameters; Sina raw and factor
  candidates are fully archived, but only the 2019 split and 2025 distribution
  have first-party source bodies. The 2020, 2021, and 2024 candidate events lack
  archivably verified first-party originals. Consequently qfq cannot be derived,
  all A--J gates cannot pass, and Issues 004--012 must not begin.
