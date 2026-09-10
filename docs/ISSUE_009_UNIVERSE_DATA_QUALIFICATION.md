# Issue 009-D0 Frozen Universe Data Qualification

Status: `BLOCKED_DATA`
Substage: `009-D0`
Locked test: not run

This report is a pre-locked-test qualification artifact. It does not report a
strategy result and does not alter the frozen universe, benchmark, strategy,
cost model, timing rule, parameter grid, or split.

## Current full-universe scan

Artifact: `artifacts/data_qualification/89d589cafb91ebdf9ccc85220ab461324ebd5af6ff85cd7974da04127050e2d7/qualification.json`

| Symbol | Raw / sessions | Ledger | PIT causal | Adjusted | Execution raw | Result |
| --- | --- | --- | --- | --- | --- | --- |
| `510300` | PASS | missing | FAIL | missing | PASS | NOT_QUALIFIED |
| `510500` | PASS | missing | FAIL | missing | PASS | NOT_QUALIFIED |
| `159919` | PASS | complete + archived | PASS | available | PASS | NOT_QUALIFIED |

`159919` remains not qualified for this D0 scan until its existing independent
cross-provider reconciliation and deterministic-reproduction evidence is
registered by the D0 audit. This is a conservative reporting state, not a
revision of its accepted Issue 003 history.

## Candidate inventory

The retained provider raw/qfq pairs are discovery-only. Their exact qfq/raw
ratios change on 2,653 sessions for `510300` and 2,785 sessions for `510500`.
They therefore cannot be treated as an event ledger or as canonical adjusted
prices. Every unresolved factor change remains a blocker until an official
event or evidence-supported provider artifact classification is recorded.

## Promotion rule

All three frozen assets must be `QUALIFIED` before a new locked-test precommit
manifest can be generated. No locked test, walk-forward result, robustness
result, or Issue 010 work is permitted while this report is blocked.
