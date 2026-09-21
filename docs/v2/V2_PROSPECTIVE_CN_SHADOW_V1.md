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

`INPUT_STATUS` becomes `FULLY_PROSPECTIVE_INPUT` only when every selected
symbol's full 60-session feature window consists of contemporaneously captured
snapshots. IC and Rank-IC use the frozen `close[T+2] / close[T+1] - 1` label and
are evaluated only after both closes exist. The 60-day signal and paper status
is research evidence, not an authorization to trade.

Automation is provided by `quant-prospective.timer`, scheduled at 18:30 and
20:30 Asia/Shanghai. The second run is an idempotent retry. `status` reads the
latest consolidated JSON without network access, while `rebuild` reconciles the
append-only ledger and hashes the immutable artifact set.

## First operational acceptance

The 2026-09-21 live smoke completed with `DAILY_RUN_COMPLETE`,
`MIXED_PROSPECTIVE_INPUT`, `SIGNAL_EMITTED`, `RECONCILED_LOCAL_ONLY` and
`INSUFFICIENT_PROSPECTIVE_EVIDENCE`. The current snapshot retained 297 usable
bars; three Tencent symbol requests failed and four CNInfo action responses had
unknown schemas. Those seven symbols did not enter the 292-name eligible cross
section. Rebuild reproduced ledger head `f92dcac1…cbf4` and artifact-set hash
`a7517f0d…4e52`. A direct systemd service invocation completed successfully and
the timer is enabled for the next session.

Engineering acceptance is therefore `OPERATIONS_LOOP_CLOSED`. Signal and
profitability acceptance remain pending real forward observations; warm-start
diagnostics never promote either status.
