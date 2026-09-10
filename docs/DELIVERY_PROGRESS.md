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
| 001 | `issue/001-akshare-etf-adapter` | baseline `53cf6d3` | PASS | Offline adapter, immutable snapshot and calendar tests | Accepted through the shared 001--003 gate |
| 002 | `issue/002-provenance-manifests` | baseline `53cf6d3` | PASS | Content-addressed raw/Parquet/manifest tests | Accepted through the shared 001--003 gate |
| 003 | `issue/003-159919-szse-recovery` | accepted `eea1e16` | PASS | Canonical raw/qfq/causal evidence chain and reconciliation tests | Issue 004 accepted as descendant |
| 004 | `issue/004-features` | accepted `8812be2` | PASS | PIT feature warm-up tests | Issue 005 accepted as descendant |
| 005 | `issue/005-portfolio-construction` | accepted `fdb9267` | PASS | Constraint and deterministic weighting tests | Issue 006 accepted as descendant |
| 006 | `issue/006-vectorbt-t1` | accepted `05c2a0d` | PASS | VectorBT T+1 order-timestamp test | Issue 007 accepted as descendant |
| 007 | `issue/007-cost-model` | accepted `59d4226` | PASS | Commission, minimum commission, spread, slippage and doubled-cost tests | Issue 008 accepted as descendant |
| 008 | `issue/008-no-lookahead` | accepted `85561e7` | PASS | T+1, ordering and causal-adjustment PIT tests | Issue 009 branch is a descendant |
| 009 | `issue/009-walk-forward` | base `85561e7`; D0 remediation | BLOCKED_DATA | Full-universe D0 qualification scan, frozen inputs, deterministic execution, fold runner and immutable experiment registry | `510300` and `510500` ledgers incomplete; locked test and Issue 010 forbidden |
| 010 | not created | — | NOT_STARTED | — | Forbidden before Issue 009 PASS |
| 011 | not created | — | NOT_STARTED | — | Forbidden before Issue 010 PASS |
| 012 | not created | — | NOT_STARTED | — | Forbidden before Issue 011 PASS |

## Current acceptance commands

```bash
uv run ruff check .
uv run ruff format --check .
uv run mypy src
uv run pytest --cov=quant_stack
```

Current full validation in the repository-local Conda Python 3.11 environment:
Ruff, formatting, strict mypy and `89 passed` with coverage. The environment is
ignored; the dependency set is synchronized from the checked-in `uv.lock`.

## Current Issue 009 review

- Substage: `009-D0 Frozen Universe Data Qualification`.
- Status reason: `MISSING_PIT_DATA_PREREQUISITE`.

- Evaluation contract SHA-256: `11869af4ab20ceec8a10c5d2e8f958114b1ca59da0da041628a1862c8b6df230`.
- Frozen inputs: universe, strategy, primary benchmark, execution and cost YAML
  files are hash-verified by the preregistration manifest before any executable
  experiment can proceed.
- The runner retains every supplied OOS fold, applies net costs on T+1-or-later
  open execution, and compares each fold against `SAME_UNIVERSE_EQUAL_WEIGHT`.
- No locked-test manifest, result, outcome classification, or robustness report
  exists yet. The runner has not read or evaluated the locked test interval.
- Before a locked run, the complete frozen universe must have one verified causal
  adjusted dataset and a valid coverage proof for the exact required interval.
  There is currently no authorization to replace missing datasets, splice
  providers, synthesize prices, or change the frozen universe.
- Current causal-data preflight: only `159919/SZSE` is present as a
  hash-verified canonical causal series (`1252a806...`); `510300/SSE` and
  `510500/SSE` are absent. This blocks the locked test without changing any
  raw/qfq artifact or treating an adjusted provider export as a PIT-safe series.
- D0 evidence progress: `510300` currently has eight verified cash-distribution
  entries (2019--2026 effective dates) and four retrospective candidates
  (2015--2018);
  `510500` has two verified share-split entries (2015 and 2022) plus one
  verified 2024, one verified 2025, and two verified 2026 cash distributions.
  Both ledgers are explicitly incomplete.
- `510300` D0 raw cross-check: independent Sina and AKShare series overlap on
  2,841 sessions; 8 OHLC differences remain after the fixed, parser-derived
  volume precision rule, so reconciliation stays blocked and no provider is
  selected or merged.
- `510500` D0 raw cross-check: independent Sina and AKShare series overlap on
  2,839 sessions; 6 OHLC differences remain under the same frozen raw-price
  comparison, so reconciliation stays blocked and no provider is selected or
  merged.
- Tushare D0 cross-check is unavailable in the current environment: its module
  is not installed and no token is configured. This is recorded without reading
  or storing a credential and does not weaken the Sina/AKShare mismatch gate.
