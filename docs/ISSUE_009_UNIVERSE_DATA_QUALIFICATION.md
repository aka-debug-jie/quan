# Issue 009-D0 Frozen Universe Data Qualification

Status: `BLOCKED_DATA`
Substage: `009-D0`
Locked test: not run

This report is a pre-locked-test qualification artifact. It does not report a
strategy result and does not alter the frozen universe, benchmark, strategy,
cost model, timing rule, parameter grid, or split.

## Current full-universe scan

Artifact: `artifacts/data_qualification/7cc66991d049d1c132d7f57684236a1e01824a088b192480dfd8be433b6f4fe6/qualification.json`

| Symbol | Raw / sessions | Ledger | PIT causal | Adjusted | Execution raw | Result |
| --- | --- | --- | --- | --- | --- | --- |
| `510300` | PASS | incomplete; 4 verified dividends | FAIL | missing | PASS | NOT_QUALIFIED |
| `510500` | PASS | incomplete; 2 verified splits | FAIL | missing | PASS | NOT_QUALIFIED |
| `159919` | PASS | complete + archived | PASS | available | PASS | NOT_QUALIFIED |

`159919` remains not qualified for this D0 scan until its existing independent
cross-provider reconciliation and deterministic-reproduction evidence is
registered by the D0 audit. This is a conservative reporting state, not a
revision of its accepted Issue 003 history.

## Candidate inventory

The retained provider raw/qfq pairs are discovery-only. Their exact qfq/raw
ratios change on 2,653 sessions for `510300` and 2,785 sessions for `510500`.
Because each relation changes on more than half of observed sessions, the D0
diagnostic classifies the whole provider-factor relation as
`PROVIDER_ARTIFACT`, not as a discrete corporate-action ledger. This does not
make either provider qfq series canonical. Discrete raw-price discontinuities
and official-announcement inventories remain independently reconcilable.

## Promotion rule

All three frozen assets must be `QUALIFIED` before a new locked-test precommit
manifest can be generated. No locked test, walk-forward result, robustness
result, or Issue 010 work is permitted while this report is blocked.
