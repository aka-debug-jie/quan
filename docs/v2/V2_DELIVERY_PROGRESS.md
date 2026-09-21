# Quant V2 Delivery Progress

EXQ equity-distribution candidates (2026-09-19): six official implementation
notices yielded record/ex-date and gross cash text. Three ex dates intersect
candidate residual intervals; factor/raw-price reconciliation remains required,
so no ledger event or classification changed. See
EXQ_001_EQUITY_DISTRIBUTION_CANDIDATES.md.

EXQ final replay implementation (2026-09-19): a new deterministic matrix binds
hash-pinned legacy qualification and compiled current evidence. It rejects
future-notice exclusions, empty provider output and unreconciled factor events;
the full candidate domain remains independently blocking until raw execution,
rule and cost evidence exist. The fixed root runner is ready to write a
content-addressed replay without exporting prices. See
EXQ_001_FINAL_REPLAY_PROTOCOL.md.

EXQ corporate field extraction (2026-09-19): 24 hash-verified PDFs produced
639 candidate sentences but only one same-sentence explicit date field. No
corporate-action ledger event or price adjustment was inferred. See
EXQ_001_CORPORATE_ACTION_EXTRACTION.md.

EXQ corporate-action leads (2026-09-19): 24 title-selected, hash-bound issuer
PDF leads are queued for accounting validation. None has record/ex-date or
cash/share terms verified, so no price adjustment or execution eligibility is
claimed. See EXQ_001_CORPORATE_ACTION_QUEUE.md.

EXQ rule-source capture (2026-09-19): four official CSRC/SSE/SZSE source
bodies and receipts are content-addressed. Security/date binding, historical ST
status, fee schedules and research cost assumptions remain pending. See
EXQ_001_RULE_CAPTURE_RESULT.md.

EXQ history revalidation (2026-09-19): 27 of 30 relevant existing reviewed
claims passed the unchanged issuer-history validator, supporting 210 of the
275 SZSE residual keys retrospectively; 65 SZSE and 3 SSE keys remain without
this support. This does not replace the frozen global funnel or qualify
execution. See EXQ_001_HISTORY_REVALIDATION.md.

EXQ full discovery (2026-09-19): all 28 fixed issuer windows completed across
64 pages (1,451 announcements). 155 candidate PDFs yielded 630 complete
page-numbered sentences without capture/extraction failure. Claim review is
pending; no additional session is classified as explained. See
EXQ_001_FULL_DISCOVERY_RESULT.md. Qualification remains BLOCKED_DATA.

EXQ pagination follow-up: all 62 discovered PDFs now have byte-verified local
copies (245 candidate sentences). The fixed sz000793 window returns 110
announcements on four pages; the first-page-only discovery was incomplete.
Pagination validation is implemented. No session or qualification upgrade is
claimed. See EXQ_001_PAGINATION_REVIEW.md.

EXQ notice review update (2026-09-19): 54 of 62 discovered PDFs were located in
existing local archives and byte-hash verified, yielding 223 complete candidate
sentences. No new session qualification is claimed. Discovery pagination and
corporate-action validation remain incomplete. See EXQ_001_LOCAL_NOTICE_REVIEW.md.

| Issue | Status | Evidence |
| --- | --- | --- |
| V2-000 Research charter | COMPLETE | Charter, dataset and experiment contracts frozen before capture |
| V2-001 Dataset registry | COMPLETE | Five pinned records, strict model, content-addressed capture and offline CLI |
| V2-002 Qlib/community import | IMPORT_READY | The pinned 565 MB archive, release manifest and extraction tree were captured in the sealed store. The immutable legacy import report remains `BLOCKED_DATA`; newer imports distinguish structural readiness from semantic qualification. |
| V2-003 PIT membership qualification | BLOCKED_DATA; FREE_AUDIT_CLOSED_ACCEPTED | Historical SZSE/PIT audit closure on 2026-09-13: SSE residual 0; SZSE 8,030/8,093 explained, 63 residual days in 23 intervals, zero conflicts. Five official CSI removal dates verified; five end boundaries corrected only in a derivative copy. This historical 63-day scope is distinct from the later authoritative full-missing-session funnel below. Full PIT qualification remains separate. No further residual or full-PIT work is scheduled under this audit. See FREE_AUDIT_CLOSURE_20260913.md. |
| V2-free-funnel | CLOSED_WITH_RESIDUAL | Frozen full replay classified 15,743 missing sessions: 15,203 official suspensions, 540 unexplained, zero conflicts and 724 intervals. Two replays had identical canonical hashes. The residual is an accepted negative result, not an automatic future research queue. Formal PIT and research remain BLOCKED_DATA. See FREE_EVIDENCE_FINAL_REPORT.md. |
| V2-004 Qlib Linear/LightGBM baseline | FORMAL_BLOCKED_DATA; LIMITED_DEV_COMPLETED | The formal two-track 20-seed protocol remains blocked and unexecuted. DEV-001 separately completed one fixed-seed CSI300 limited-development Linear/LightGBM run with Alpha158, content-addressed evidence, view and results, plus exact model reload and prediction rebuild. It is not promotion or formal qualification. See DEV_001_RESULT.md. |
| V2-005 Global ETF research dataset | CAPTURED_RESEARCH_ADJUSTED_ONLY | Seven Yahoo snapshots share 3,884 daily sessions; report `7d2022ca…` is locally archived. |
| V2-006 V2-A trend / dual momentum | IMPLEMENTED_RESEARCH_SIGNAL_ONLY | Frozen monthly 12-1 signal contract produced 175 signals from Yahoo report `7d2022ca…`, output `7b5ca5ff…`; it cannot produce an execution backtest or candidate claim. |
| V2-007 V2-B deterministic factors | BLOCKED_DATA | PIT fundamental-evidence and transparent factor-ranking interfaces exist; no qualified PIT fundamentals or real-stock ranking exists. |
| V2-008 V2-B Qlib models | BLOCKED_DATA | Linear, LightGBM and XGBoost are frozen in the 20-seed model contract; training waits for V2-002/003 and reproducible V2 dependencies. |
| V2-009 V2-C residual alpha | BLOCKED_DATA | Causal residual-label and cost-adjusted incremental-net-return gates are implemented; no comparison can run before V2-007/008 evidence exists. |
| V2-010 External historical blind test | BLOCKED_DATA; GLOBAL_ETF_USD_INITIALIZED | CNY/CSI500 contracts remain `PENDING_SOURCE_APPROVAL`. The selected first path, GLOBAL_ETF_USD, has an offline qualification receipt `0b982…a6fa96` that records the seven missing artifacts (approval, raw manifest, calendar, corporate actions, PIT membership, costs and reproduction). A read-only provider comparison identifies EODHD as the first candidate, pending user account and license acceptance; it is not source approval. No source capture or historical return test has run. See V2_010_GLOBAL_ETF_USD_INITIAL_QUALIFICATION.md and V2_010_GLOBAL_ETF_USD_PROVIDER_OPTIONS.md. |
| V2-011 LEAN independent reconciliation | BLOCKED_ENGINE | Exact normalized fixture reconciliation is implemented; the registered LEAN fixture has not been captured or validated. |
| V2-012 Champion / Challenger | BLOCKED_DATA | Immutable two-candidate selection applies strict external data, reproduction, LEAN and relative-benchmark gates; no strategy is eligible. |
| V2-013 Independent V2 paper account | BLOCKED_DATA | V2-only CNY/USD account namespace and Champion gate exist; no account has been created because no `PAPER_CANDIDATE` exists. |
| V2-014 RD-Agent constrained experiments | IMPLEMENTED_PROPOSAL_ONLY | Immutable preregistration proposals are permitted; data access, network, training, backtests, promotion and account actions are rejected. |
| V2 research roadmap | PLANNING_ONLY | `V2_RESEARCH_ROADMAP_PROMPTS.md` defines ordered, separately authorized task prompts from AF-001 through PORT-001. It changes no current gate, contract or research status. |
| AF-001 interpretable factor screen | COMPLETED_LIMITED_DEV_DIAGNOSTICS | The frozen 16-factor Alpha158-only registry was evaluated once on the existing CSI300 development view: 10 are `CANDIDATE_PENDING_AF002`, 6 are `REJECTED_NO_STABLE_SIGNAL`; result `d89d25f0…16e62`. This is not formal promotion, uses no raw OHLCV or CSI500, and leaves formal status unchanged. See AF_001_PROTOCOL.md and AF_001_RESULT.md. |
| AF-002 walk-forward stability and redundancy | COMPLETED_LIMITED_DEV_DIAGNOSTICS | Frozen chronological development folds and redundancy rules retained 7 low-redundancy diagnostics from the AF-001 candidate set; result `738aa277…3c47`. Industry and market-cap exposure remain `NOT_AVAILABLE_IN_APPROVED_VIEW`, so no exposure claim is made. This uses no CSI500, portfolio, parameter-search or formal-status action. See AF_002_PROTOCOL.md and AF_002_RESULT.md. |
| AF-003 combinations and fixed-model increment diagnostics | COMPLETED_LIMITED_DEV_DIAGNOSTICS | Fixed expanding training folds retained `equal_weight_zscore` as the one simple development diagnostic and found `NO_STABLE_ML_INCREMENT` across Ridge, ElasticNet, LightGBM and XGBoost; result `5aa2fe8b…7624`. This is fully touched development reuse, contains no portfolio return or CSI500, and leaves formal status unchanged. See AF_003_PROTOCOL.md and AF_003_RESULT.md. |
| EXQ-001 candidate-scope qualification | BLOCKED_DATA | The frozen seven-factor AF-003 scope was bound to actual derivative CSI300 membership, feature lookbacks, label T+1/T+2 dependencies and frozen free-evidence artifacts. It has 278 exact free-residual dependency intersections and 671 official-suspension intervals in its required range. Raw OHLCV, official corporate actions, ST, and frozen execution semantics remain absent; no evidence was supplemented. Result `d76df755…7862`; formal PIT/research remain BLOCKED_DATA and CSI500 remains NOT_STARTED. See EXQ_001_PROTOCOL.md and EXQ_001_RESULT.md. |
| EXQ-001 independent raw capture | CAPTURE_COMPLETE; NOT_QUALIFYING | AKShare/Eastmoney archived 278 exact candidate-residual requests with zero provider failures, but every response was an empty daily-bar result. This is independent-provider absence evidence only; it does not establish official suspension, PIT-safe exclusions, corporate actions, or executable prices. Receipt 47c730bd…a9ed; formal status is unchanged. See EXQ_001_RAW_PROVIDER_RESULT.md. |
| EXQ-001 final replay | BLOCKED_DATA; REPLAYED_WITH_RESIDUAL | The initial restricted replay blocked all eight execution domains. The 2026-09-21 Tencent incremental replay then validated independent raw evidence and released only `raw_execution`; matrix `839495…c451`, residual `79ea90…0dcc` and summary `d7925f…d2f7` retain the other seven domains as blocking across all 278 exact residual keys and the 543-symbol full domain. Each remaining domain covers the same 31 symbol scopes. It is a negative candidate-qualification result, not a formal-status change. See EXQ_001_TENCENT_REPLAY_RESULT.md. |
| BT-001 executable portfolio backtest | NOT_STARTED; PRECONDITION_FAILED | EXQ-001 is terminally `BLOCKED_DATA; REPLAYED_WITH_RESIDUAL`, so the required candidate-scope qualification is absent. No raw data, CSI500, sealed samples, backtest configuration, execution simulation, return result or `INVALID_BACKTEST` artifact was created. The remaining blockers are corporate actions, trading status, price limit, board lot, T+1, liquidity and cost model; inputs are matrix `839495…c451`, residual `79ea90…0dcc` and summary `d7925f…d2f7`. Formal PIT/research remain `BLOCKED_DATA` and CSI500 remains `NOT_STARTED`. |

V1 remains on its existing release-candidate branch and account paths. V2 writes
only below `docs/v2`, `configs/v2`, `src/quant_stack_v2`, `data/external` and
`artifacts/v2`, plus the minimal root CLI/package wiring needed to expose V2.

V2-NEXT-02 has a separate limited development path; it does not promote any row above:

| Status field | Value |
| --- | --- |
| IMPLEMENTATION_STATUS | SYNTHETIC_E2E_VERIFIED |
| REAL_DATA_VIEW_STATUS | NOT_EXPORTED_MISSING_SPEC_AND_AUTHORITY |
| DEV_SMOKE_STATUS | SYNTHETIC_VERIFIED; REAL_NOT_RUN |
| FORMAL_RESEARCH_STATUS | BLOCKED_DATA; CSI500_NOT_STARTED |

See `V2_NEXT_02_DELIVERY.md` and the complete upfront matrix in
`V2_NEXT_02_READINESS.md`. Real Alpha158/source normalization and use approval
remain unimplemented/unapproved; the original sealed runner still refuses execution.

DEV-001 subsequently filled the explicitly approved limited-development scope without
overwriting the V2-NEXT-02 synthetic contract. Its separate status is:

| Status field | Value |
| --- | --- |
| IMPLEMENTATION_STATUS | REAL_QLIB_ADAPTER_AND_STAGED_RUNNER_VERIFIED |
| REAL_DATA_VIEW_STATUS | CSI300_LIMITED_VIEW_EXPORTED |
| DEV_SMOKE_STATUS | DEV_REAL_RUN_COMPLETED |
| FORMAL_RESEARCH_STATUS | BLOCKED_DATA; CSI500_NOT_STARTED |

The run used the fixed 2015--2019 training and 2020 validation candidates, excluded
the first 20 validation sessions, and retained `BLOCKED_DATA` for incomplete full-PIT
membership qualification. It produced signal diagnostics only; no portfolio-return,
promotion, sealed-test or live-trading conclusion was generated.

Current external metadata pins:

- `chenditc/investment_data` release `2026-09-10`, commit `b8c129b...`;
- `microsoft/qlib` release `v0.9.7`, commit `79633dd...`;
- `AI4Finance-Foundation/FinRL-Meta` release `v0.3.6`, commit `15405db...`;
- `QuantConnect/Lean` release `v2.4.0.1`, commit `8ee075a...`;
- `datasets/finance-vix` commit snapshot `07b0768...`.

The Qlib community archive has been captured only inside the sealed store. It remains
unqualified for V2 research until its independent evidence gates pass.

Acceptance: 27 focused offline registry tests pass with 81% branch-aware module
coverage. Formal dataset validation
remains fail-closed until each non-fixture dataset has captured bytes, verified
coverage and an explicit `QUALIFIED` status through a later reviewed change.

V2-002--V2-004 require the administrator-run `scripts/v2/setup_sealed_holdout.sh`.
The sealed directory has been provisioned. Its data remain visible only to the
evaluator identity; this repository does not downgrade CSI500 evaluation to an
ordinary local directory.
