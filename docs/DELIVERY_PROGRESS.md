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
| 009 | `issue/009-walk-forward` | base `85561e7`; current `0f5e09c` | IN_PROGRESS | Frozen evaluation contract/input hashes; deterministic target execution; fold runner; 89 offline tests pass | Locked test has not run; Issue 010 remains forbidden |
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
