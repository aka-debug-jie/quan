# Delivery Progress

## Current authoritative status

Issues 001–011 are accepted. Issue 012 is a release candidate pending explicit
timer enablement and the planned 15-day operations observation. RC-01 fixes the
paper month-end calendar gate, record-date dividend entitlement and receivable
accounting, actual-generation/backfill metadata, install-versus-enable separation,
and CI coverage for `codex/**` and `issue/**` pushes. Issue 009 remains
`PASS_CONTROLLED_RECOVERY` with `NO_EVIDENCE_OF_EDGE`; no strategy parameter or
locked-test evidence changed.

RC-01 local acceptance and GitHub CI run `34562043209` both pass. Merge,
default-branch change, V1 tag and timer enablement remain intentionally unperformed.

## V3 controlled-recovery result

Authorization `f44f878b...` executed once under code `d865221` and authorization
commit `cc98d5f`. Both preauthorized fresh Python child builds retained all 16
runs and produced byte-identical prepared output; strict publication and readback
passed with no failure receipt.

- Issue 009 gate: `PASS_CONTROLLED_RECOVERY`.
- Frozen research outcome: `NO_EVIDENCE_OF_EDGE`.
- Holdout: `NOT_FRESH_PREVIOUSLY_ACCESSED`; fresh confirmation is not available.
- V2 remains `INVALID_RESEARCH_RESULT`; its receipt hashes are unchanged.
- Live trading remains forbidden; no result-dependent tuning is authorized.
- The 2026-10 through 2028-03 prospective validation is separate and non-blocking.
- Issue 010 paper-platform engineering is now permitted but has not started.

See `docs/ISSUE_009_CONTROLLED_RECOVERY_RESULT_V3.md` for metrics, hashes,
reproduction evidence, limitations and the formal conclusion.

## V3 controlled-recovery preflight

The user authorized one transparent, no-tuning V3 controlled recomputation and
a separate non-blocking 18-month prospective validation. The V3 contract and
experiment config bind the exact failed V2 precommit/data/evidence, unchanged
research definitions, 16 ordered runs, exact runtime, two fresh Python child
processes, pending-before-comparison semantics, receipt-only publication, and
the `NOT_FRESH_PREVIOUSLY_ACCESSED` label.

Pre-authorization validation: Ruff, format and strict mypy PASS; **149 tests
passed** with **71.54%** combined statement/branch coverage. This is only the
preflight. No V3 authorization file or real controlled result existed when this
entry was written; the historical V2 result remains invalid.

## Prospective protocol preparation

The former prospective draft is superseded as an execution source. The user
authorized the bounded V3 controlled-recovery route on 2026-09-11 and retained
2026-10 through 2028-03 as a separate, non-blocking prospective validation.
The tracked V3 contract/config freeze exact V2 predecessor evidence, unchanged
research definitions, two fresh-process builds, strict equality and publication
rules. This authorization does not alter the historical V2 invalid result or
claim that its interval is a fresh holdout.

## 2026-09-11 runner-hardening addendum

Branch `codex/issue009-runner-hardening`, baseline `d70e4da`:
`PASS_SYNTHETIC_ONLY` for strict serialization/schema, immutable per-run checkpoints,
failure receipts and computation-free synthetic publication recovery. Full validation:
Ruff / format / strict mypy PASS; **144 tests passed**, coverage **73.21%**.
Two independent synthetic 16-run builds have identical output bytes.

See `docs/ISSUE_009_RUNNER_HARDENING.md` for exact local evidence paths, hashes,
the bounded Decimal affordability correction, and the unapproved next-protocol decisions.
This addendum supersedes the older test count below, not the historical Issue 009 result.
At that hardening checkpoint, real Issue 009 remained `BLOCKED_CONTAMINATED` and
V2 failure receipts were unchanged. The later V3 contract is a separately authorized
controlled recomputation, not authorization from the engineering recovery command.

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
| 009 | `codex/issue009-runner-hardening` | code `d865221`; authorization `cc98d5f` | PASS_CONTROLLED_RECOVERY | D0 PASS; two V3 builds identical; frozen result `NO_EVIDENCE_OF_EDGE` | Accepted for platform engineering; not a fresh holdout or edge claim |
| 010 | `codex/issue009-runner-hardening` | `acc0198`, `725f86a` | PASS | SQLite WAL, hash-chain, raw fills, actions, reconciliation and idempotency tests | No live orders |
| 011 | `codex/issue009-runner-hardening` | `acc0198` | PASS | Offline single-file HTML report, SVG and evidence rendering tests | Local report artifacts only |
| 012 | `codex/issue009-runner-hardening` | `acc0198` | READY_TO_INSTALL | User systemd units, catch-up workflow, lock, failure receipts and unit validation | Install script has not been run |

## Current acceptance commands

```bash
uv run ruff check .
uv run ruff format --check .
uv run mypy src
uv run pytest --cov=quant_stack
```

Current full validation in the repository-local Conda Python 3.11 environment:
Ruff, formatting, strict mypy and `126 passed` with coverage. The environment is
ignored; the dependency set is synchronized from the checked-in `uv.lock`.

## Current Issue 009 review

- Substage: `009 Locked-Test V2`.
- Status: `D0 PASS`; locked-test V2 `INVALID_RESEARCH_RESULT`.

- V1 evaluation contract SHA-256:
  `11869af4ab20ceec8a10c5d2e8f958114b1ca59da0da041628a1862c8b6df230`.
- V2 supplemental contract SHA-256:
  `e0cbb2c91e522d5a4f76a58429eaa316b8c89e992c378279bbb952b8208c40b1`.
- Frozen inputs: universe, strategy, primary benchmark, execution and cost YAML
  files are hash-verified by the preregistration manifest before any executable
  experiment can proceed.
- The runner retains every supplied OOS fold, applies net costs on T+1-or-later
  open execution, and compares each fold against `SAME_UNIVERSE_EQUAL_WEIGHT`.
- V2 precommit `d1c3c371864885134f4a733cebdc09b0fedcd2ca69ad7a8a9c1898c4374fe7c6`
  was committed at `a9b96c0` and consumed exactly once. The runner accessed the
  locked interval, then failed before persisting formal metrics because a
  registry payload contained a non-serialized Python `date`.
- Final D0 qualification artifact:
  `66ed03b7fda4057fac1a1f5ab916443d66fe87fe30ab5a6903e67433cc20978a`.
  `159919`, `510300`, and `510500` are all `QUALIFIED`.
- `510300` has 12 verified dividends and zero unexplained events. Its 2015
  original SSE notice establishes the 2015-01-20 ex-date and CNY 0.35 per 10
  units. `510500` has four verified dividends, two verified splits, and zero
  unexplained events.
- Complete SSE official raw series are the single canonical sources for the two
  SSE assets. AKShare/Eastmoney remains an independent full-history cross-check;
  Sina adjudicates its five 2020 discrepancies per asset. All official values
  are corroborated, with zero rejected or unexplained records and no splicing.
- Causal output SHA-256 values are `7bf2e960...` for `510300`, `35e94885...`
  for `510500`, and `9b096bc9...` for `159919`. Isolated rebuilds at code
  commit `686a626` reproduce all three output hashes exactly.
- The failure is recorded as `INVALID_RESEARCH_RESULT`; the same precommit and
  2024-01-02--2026-09-09 holdout cannot be rerun. Issue 009 remains blocked, and
  Issue 010-012 cannot start. A new locked protocol requires genuinely unused
  observations after 2026-09-09.
