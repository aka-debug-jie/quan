# Quant V2 Delivery Progress

| Issue | Status | Evidence |
| --- | --- | --- |
| V2-000 Research charter | COMPLETE | Charter, dataset and experiment contracts frozen before capture |
| V2-001 Dataset registry | COMPLETE | Five pinned records, strict model, content-addressed capture and offline CLI |
| V2-002 Qlib/community import | BLOCKED_SYSTEM_ACCESS | Offline importer and capture command implemented; `/srv` sealed root is not yet administrator-provisioned, so the 565 MB archive has not been captured. Even after capture, Qlib factor files remain insufficient until their reconstruction semantics have archived evidence. |
| V2-003 PIT membership qualification | BLOCKED_DATA | Research range is frozen at 2015-01-01 through the 2026-09-10 snapshot before model execution. Historical `sht00018` remains preserved and is classified `pre_research_range`; factor semantics evidence is still required. |
| V2-004 Qlib Linear/LightGBM baseline | BLOCKED_DATA | Frozen 20-seed precommit and sealed aggregate-result gate implemented; no model has run before V2-003 qualification. The pinned V2 dependency installation also remains incomplete after two PyPI transport timeouts. |
| V2-005 Global ETF research dataset | CAPTURED_RESEARCH_ADJUSTED_ONLY | Seven Yahoo snapshots share 3,884 daily sessions; report `7d2022ca…` is locally archived. |
| V2-006 V2-A trend / dual momentum | IMPLEMENTED_RESEARCH_SIGNAL_ONLY | Frozen monthly 12-1 signal contract produced 175 signals from Yahoo report `7d2022ca…`, output `7b5ca5ff…`; it cannot produce an execution backtest or candidate claim. |
| V2-007 V2-B deterministic factors | BLOCKED_DATA | PIT fundamental-evidence and transparent factor-ranking interfaces exist; no qualified PIT fundamentals or real-stock ranking exists. |
| V2-008 V2-B Qlib models | BLOCKED_DATA | Linear, LightGBM and XGBoost are frozen in the 20-seed model contract; training waits for V2-002/003 and reproducible V2 dependencies. |
| V2-009 V2-C residual alpha | BLOCKED_DATA | Causal residual-label and cost-adjusted incremental-net-return gates are implemented; no comparison can run before V2-007/008 evidence exists. |
| V2-010 External historical blind test | BLOCKED_DATA | CNY/CSI500 and USD/global-ETF raw qualification contracts are registered as `PENDING_SOURCE_APPROVAL`; no source capture or historical return test has run. |
| V2-011 LEAN independent reconciliation | BLOCKED_ENGINE | Exact normalized fixture reconciliation is implemented; the registered LEAN fixture has not been captured or validated. |
| V2-012 Champion / Challenger | BLOCKED_DATA | Immutable two-candidate selection applies strict external data, reproduction, LEAN and relative-benchmark gates; no strategy is eligible. |
| V2-013 Independent V2 paper account | BLOCKED_DATA | V2-only CNY/USD account namespace and Champion gate exist; no account has been created because no `PAPER_CANDIDATE` exists. |
| V2-014 RD-Agent constrained experiments | IMPLEMENTED_PROPOSAL_ONLY | Immutable preregistration proposals are permitted; data access, network, training, backtests, promotion and account actions are rejected. |

V1 remains on its existing release-candidate branch and account paths. V2 writes
only below `docs/v2`, `configs/v2`, `src/quant_stack_v2`, `data/external` and
`artifacts/v2`, plus the minimal root CLI/package wiring needed to expose V2.

Current external metadata pins:

- `chenditc/investment_data` release `2026-09-10`, commit `b8c129b...`;
- `microsoft/qlib` release `v0.9.7`, commit `79633dd...`;
- `AI4Finance-Foundation/FinRL-Meta` release `v0.3.6`, commit `15405db...`;
- `QuantConnect/Lean` release `v2.4.0.1`, commit `8ee075a...`;
- `datasets/finance-vix` commit snapshot `07b0768...`.

No full external market archive has been downloaded or qualified.

Acceptance: 27 focused offline registry tests pass with 81% branch-aware module
coverage. Formal dataset validation
remains fail-closed until each non-fixture dataset has captured bytes, verified
coverage and an explicit `QUALIFIED` status through a later reviewed change.

V2-002--V2-004 require the administrator-run `scripts/v2/setup_sealed_holdout.sh`.
The current user has no non-interactive sudo permission, so this repository does
not silently downgrade CSI500 sealed evaluation to an ordinary local directory.
