# V2-010 global ETF USD initial qualification

Status: `BLOCKED_DATA`.

The existing fail-closed qualification command was run offline against
`global_etf_usd_external_v1`. It created no provider request, market-data
download, training job, backtest or paper account.

| Item | Value |
| --- | --- |
| Qualification receipt | `0b98236010ccfe469c9e4c8eb00b07855e3f1b73e1c013a360da5268e7a6fa96` |
| Market | `GLOBAL_ETF_USD` |
| Currency | `USD` |
| Source approval | `PENDING_SOURCE_APPROVAL` |

The receipt identifies seven required gaps: source approval, immutable raw
manifest, local calendar, corporate-action evidence, PIT membership, frozen
cost model and deterministic reproduction. The archived Yahoo data remain
adjusted-price research inputs only; they are not substituted for any gap.

The next action requires an explicit provider and data-use decision. After it
is fixed, the same validator will accept only hash-verified artifacts rooted
under the reviewed external-evidence directory. It will remain `BLOCKED_DATA`
until every required artifact is present and valid.
