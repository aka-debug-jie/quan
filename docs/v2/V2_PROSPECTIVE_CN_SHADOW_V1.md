# V2 prospective CN shadow v1

The historical V2 line remains `NO_FORMAL_DATA_QUALIFICATION`. This independent
forward-only line does not reopen EXQ-001, BT-001, CSI500, Champion promotion or
any live-broker path. The candidate remains AF-003 `equal_weight_zscore` with
the seven preregistered factors.

The operational entry point is:

```bash
uv run quant v2 prospective run-daily --allow-network
```

It captures the current CSI300 membership, Tencent raw daily bars and status,
CNInfo corporate actions and a Tencent CSI300 benchmark. Every normalized input
is content-addressed with provider, retrieval timestamp and SHA-256. A first run
also creates a 65-session retrospective feature warm start whose status is
always `WARM_START_NON_FORMAL`.

The daily sequence fills yesterday's day-only orders at today's raw open,
applies evidence-linked corporate actions, values raw-close holdings, computes
the T-close signal and creates orders for the next explicit exchange session.
The account is local SQLite only. It applies board quantity rules, sell tax,
transfer fee, commission, spread and slippage; it has no transport capable of
sending a real order.

`INPUT_STATUS` becomes `FULLY_PROSPECTIVE_INPUT` only when every symbol in the
scored cross-section has the exact expected 60-session SSE/SZSE calendar window,
every row is contemporaneously captured and the current capture is complete.
The Top20 alone cannot promote the status. IC and Rank-IC use the frozen
`close[T+2] / close[T+1] - 1` label and are evaluated only after both closes
exist. The 60-day signal and paper status is research evidence, not an
authorization to trade.

The existing `paper/strategy.sqlite3` is the `engineering_warm_start` account.
It is never relabelled as formal evidence. On the first fully prospective,
complete input, `paper/fully_prospective_v1.sqlite3` starts from the original
cash and an empty position. Once started it keeps a continuous NAV, while a
later mixed-input day cannot create a new formal target.

Corporate-action observations form an immutable, versioned knowledge view as
of each receipt timestamp. A later-discovered historical action may correct
future feature histories but never rewrites an earlier signal or order. A
conflict, or a late action intersecting an already booked holding, fails closed
as `ACTION_RECONCILIATION_REQUIRED`.

Automation is provided by `quant-prospective.timer`, scheduled at 18:30 and
20:30 Asia/Shanghai. The second run is an idempotent processing-recovery retry:
it fetches only when the first run produced no receipt. A partial first receipt
remains canonical and `DEGRADED_PROVIDER_FAILURES`; it is not silently refreshed.
`status` reads the latest consolidated JSON without network access, while
`rebuild` reconciles both append-only ledgers and hashes the immutable artifact
set.

`quant v2 prospective acceptance-status` emits a redacted manifest containing
the validated commit, CI reference, local test/coverage summary, configuration
and systemd hashes, receipt hashes, per-account ledger heads and the remaining
runtime evidence. It contains no raw prices, symbols, positions or absolute
paths.

## First operational acceptance

The 2026-09-21 live smoke completed with `DAILY_RUN_COMPLETE`,
`MIXED_PROSPECTIVE_INPUT`, `SIGNAL_EMITTED`, `RECONCILED_LOCAL_ONLY` and
`INSUFFICIENT_PROSPECTIVE_EVIDENCE`. The current snapshot retained 297 usable
bars; three Tencent symbol requests failed and four CNInfo action responses had
unknown schemas. Those seven symbols did not enter the 292-name eligible cross
section. Rebuild reproduced ledger head `f92dcac1…cbf4` and artifact-set hash
`a7517f0d…4e52`. A direct systemd service invocation completed successfully and
the timer is enabled for the next session.

This first smoke establishes an `OPERATIONS_LOOP_RC`, not final closure: no
opening fill was due, no real two-sided rebalance occurred and the branch had no
remote CI run. Closure additionally requires green remote CI, one real T+1 fill,
one naturally occurring sell-plus-buy rebalance and a matching rebuild. Signal
and profitability acceptance remain pending real forward observations;
warm-start diagnostics never promote either status.
