# Issue 009-D0 Frozen Universe Data Qualification

Status: `BLOCKED_DATA`
Substage: `009-D0`
Locked test: not run

This report is a pre-locked-test qualification artifact. It does not report a
strategy result and does not alter the frozen universe, benchmark, strategy,
cost model, timing rule, parameter grid, or split.

## Current full-universe scan

Artifact: `artifacts/data_qualification/53c083a70c62b47cef29549081ef5f801e4fd3c2a188efe1f60b004ba59889c0/qualification.json`

| Symbol | Raw / sessions | Ledger | PIT causal | Adjusted | Execution raw | Result |
| --- | --- | --- | --- | --- | --- | --- |
| `510300` | PASS | incomplete; 4 verified dividends | FAIL | missing | PASS | NOT_QUALIFIED |
| `510500` | PASS | incomplete; 3 verified events | FAIL | missing | PASS | NOT_QUALIFIED |
| `159919` | PASS | complete + archived | PASS | available | PASS | QUALIFIED |

`159919` passed the D0 cross-provider and reproduction gates: report
`ab424736c7ffbd1e1dfe517e7cc2f02f85609c56da5d6ac30bfe067b8ca2d739`
records 201 overlapping sessions with zero mismatch; reproduction artifact
`8ac4974e31a59b401444fc3dc00e6fff05f8837492dff982c7246e9623ad5938`
recreates the same causal manifest and output SHA-256. This does not alter its
accepted Issue 003 history.

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
