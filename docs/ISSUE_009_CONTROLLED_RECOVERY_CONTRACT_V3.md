# Issue 009 Controlled Recovery Contract V3

Status: `PREREGISTERED_CONTROLLED_RECOVERY`  
Authorized: 2026-09-11, before the V3 recovery execution.  
This supplement does not modify or erase the V2 contract, precommit, attempt, or failure.

## Why this is a recovery, not a fresh holdout

V2 accessed the 2024-01-02 through 2026-09-09 locked interval and completed the
calculations in memory, but failed before persisting a formal result because a
`date` was not JSON serializable. No formal metrics were retained. The interval
is therefore not described as untouched, fresh, or independent in V3.

The user explicitly authorizes one transparent recomputation after runner
hardening. There is no claim that the engineering failure restores the original
holdout status. V3 results must be labelled `CONTROLLED_RECOVERY_RESEARCH` and
must cite both V2 failure receipts.

## Immutable predecessor identity

- V2 precommit ID: `d1c3c371864885134f4a733cebdc09b0fedcd2ca69ad7a8a9c1898c4374fe7c6`.
- V2 precommit file SHA-256: `0af4dc26b5f72e947830fa6aac3b1dbc3d826a6bc2eeeae5874dfe77329c34c1`.
- V2 attempt SHA-256: `ee0a73f596b7dfc79892c919526f1fa5845c3e40325726d6804c35dc4af1195e`.
- V2 failure SHA-256: `f363c065c07ed96e44b5136326c9b6773d6e5114d2ca5c4092af1ba3734a7820`.
- V2 data snapshot ID: `6f33e58c7681a3444d05933d7605672a22940ca5a5039b748d962c419fea4750`.
- V2 result remains `INVALID_RESEARCH_RESULT`; V3 cannot relabel that attempt.

V3 must use exactly this D0-qualified data snapshot. Any different asset,
manifest, ledger, causal output, qualification report, source registry, or
date interval is outside this authorization and must fail before calculation.

## Frozen research definition

V3 copies V2 without changing the universe, benchmark, strategy, parameter
grid, time splits, cost model, execution delay, sensitivity windows,
classification thresholds, or seed.

The only calculation-path correction relative to the failed V2 code is the
documented Decimal affordability boundary: if division rounds a maximum buy
upward by one representable Decimal unit, the notional moves down one unit and
the unchanged frozen cost formula is recalculated. This prevents a microscopic
negative cash balance; it does not alter any cost rate, minimum, price, signal,
target weight, or tolerance. It is frozen before V3 result access and tested on
both sides of the minimum/variable commission boundary.

- Historical selection ends 2023-12-29. The six V2 rolling three-year/one-year
  OOS folds remain exactly as listed in V2.
- Controlled-recovery interval: 2024-01-02 through 2026-09-09 inclusive.
- Last locked signal date: 2026-08-31.
- Primary: 200-session trend, 12-month momentum, 60-session volatility,
  select two; five V2 parameter neighbours are all retained.
- Primary execution is T+1 open; T+2 and doubled-cost stresses remain required.
- Start and end sensitivities each remove 21 sessions.
- Same-universe monthly equal-weight benchmark and all mandatory costs remain.
- Every window starts in cash. No result-dependent rerun, parameter change,
  ablation, tolerance change, asset replacement, or selective omission is allowed.
- The accounting model remains fractional-notional causal-adjusted accounting
  with immutable raw-open fill audit. It is not broker custody accounting.

The existing nine-condition decision rule remains unchanged. A valid negative
result is `NO_EVIDENCE_OF_EDGE`; engineering success does not require profit.

## Exactly-once recovery execution

V3 is a distinct precommit whose identity includes this contract, the exact V2
predecessor identities, frozen code/config/data hashes, and recovery mode.
The normal V2 entrypoint must continue to reject the consumed interval.

One V3 parent attempt is authorized. Before reading raw or causal bytes it must:

1. atomically claim the V3 precommit in the unique repository authority;
2. verify the archived V2 attempt and failure hashes;
3. persist two complete ordered execution plans, `build_a` and `build_b`.

Both builds are preauthorized parts of the same attempt. They run in two fresh
Python child processes with independent in-memory state and output directories.
Each must independently load the same immutable inputs, execute all 16 declared
runs, validate strict schemas, and retain every step. Build B is solely a deterministic reproduction
check, not a second statistical attempt. Its result must never be selected over A.

The runtime additionally freezes Python 3.11.15, pandas 3.0.5, NumPy 2.4.6,
PyArrow 23.0.1, `PYTHONHASHSEED=0`, `TZ=UTC`, and the hashes of
`pyproject.toml`, `uv.lock`, and `.python-version`. OMP, OpenBLAS, MKL and
NumExpr thread counts are each frozen to one.

Before registry publication, the complete prepared bytes from A and B must be
identical. A mismatch, missing step, exception, or incomplete build invalidates
the V3 attempt; no additional recomputation or third build is authorized.
Each prepared child result remains `PENDING_CONTROLLED_RECOVERY`; it must not
claim the Issue gate passed. Only build A is registered and converted to
`PASS_CONTROLLED_RECOVERY` after equality succeeds. A reproduction receipt must
record both prepared hashes, source/precommit identity, and equality.

Before any registry write, the parent writes `publication_anchor.json`, binding
the hashes of `reproduction.json` and the two child exit-code receipt. The
controlled scope cannot use the generic prepared-result publisher. Both the
normal V3 publication and any later mechanical publication recovery must enter
through the receipt-enforcing controlled publisher. The recovery CLI derives
the fixed authority and registry paths and does not accept a caller-computed
prepared or reproduction hash as its trust source.

If both complete prepared files already exist and a later registry/final-write
failure occurs, pure mechanical publication recovery is allowed only from the
hashes anchored in the immutable parent publication anchor. It must not read market
data or call the simulator. Partial computation cannot be resumed or supplemented.

## Result interpretation

Passing code, data, completeness, deterministic-reproduction and classification
checks yields `ISSUE_009_PASS_CONTROLLED_RECOVERY`, paired with either frozen
strategy outcome. It does not yield `FRESH_HOLDOUT_PASS` and must not be described
as independent confirmation. The report must separately show engineering status,
research outcome, evidence scope, all fold metrics, stresses, benchmark comparison,
and limitations.

## Non-blocking 18-month prospective validation

The prospective evidence line is frozen separately from V3 recovery:

- observation months: 2026-10 through 2028-03, 18 complete calendar months;
- exact session boundaries will be resolved only from verified local official
  exchange calendars;
- the strategy, universe, benchmark, costs and parameters above remain fixed;
- 2024-01-02 through 2026-09-30 may provide trailing-feature warm-up only;
  it cannot contribute starting positions or performance and cannot support tuning;
- the first eligible prospective signal is the verified October 2026 natural
  month-end close, executing no earlier than its following trading-session open;
- no early stopping, window extension, selective reporting or parameter change
  is allowed after observing prospective performance;
- ongoing data qualification may not expose or use strategy performance;
- the future result is reported as a separate prospective validation, never
  merged with V3 to strengthen the controlled-recovery label.

This monitoring does not block engineering work or a valid V3 controlled-recovery
Issue 009 acceptance. It also cannot retroactively upgrade V3 to a fresh holdout.

Issue 010-012 remain outside this contract and may start only after the V3 report
records `ISSUE_009_PASS_CONTROLLED_RECOVERY` and the repository governance accepts
that status as the Issue 009 gate.
