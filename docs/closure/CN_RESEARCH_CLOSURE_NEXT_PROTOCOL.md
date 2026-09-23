# CN Research Closure Next protocol

Status: `REGISTERED_BEFORE_CLOSURE_RETURNS`. The machine-readable authority is
`configs/closure/cn_research_closure_next_v1.yaml`. This registration follows the
already observed Quant Upgrade V1 results. It is a retrospective evidence repair,
not a fresh holdout or the original preregistration.

The 51 previously registered runs retain their frozen strategy, dynamic universe,
scores, dates, T+1/T+2 timing, cash, execution, transaction costs and matched
benchmarks. A new evidence and engine revision applies identically to candidate
and benchmark accounts. The original 51 result identities and 19 pre-fix
engineering artifacts are retained unchanged. Cache reuse requires exact input,
code, semantics and output-integrity matches; otherwise a new run is required.

The first complete repair revision exposed an execution defect: order IDs
contained each run's content hash, and the account sorted same-side fills by
those IDs. A factual evidence revision could therefore change which buy was
funded when cash was scarce, even in runs that never held the new event. The
repaired execution order is sells first, then buys, ordered by symbol, signal
date and quantity. It is an engineering correction applied to candidates and
benchmarks together, not a selected strategy change. The earlier valid, failed
and partial revision artifacts remain available for before/after inspection.

One post-result diagnostic control is registered before this revision's returns:
`COND_FILTER_LIQ50_D20_EQ`. On a day when the frozen conditional-reversal gate
has at least 50 eligible names, it selects the 50 highest `mean_amount_60` names
within that *same* gated set, with symbol-ascending ties and equal weights.
The rebalance interval is 20 sessions and all four frozen cost/delay scenarios
apply. It tests whether conditional filtering or reversal ordering explains an
observed difference. It does not replace the original B50 matched benchmark,
join the eight-candidate formal promotion family, or authorize deployment.

The eight original candidates retain their original 21-session paired-block,
10,000-replication, seed-20260922, Holm-corrected decision family. Invalid
comparisons have no measured p-value or interval. An internal p=1 placeholder
may preserve family size, but is never published as a measurement. Candidate-only
capital-scale runs, if triggered by the inherited gate, are absolute capacity
diagnostics because no same-capital matched benchmark was preregistered.

The first evidence batch targets common B50/B100 and condition-reversal/AF7
avoidance blockers. Evidence is selected by missing accounting fields and run
dependencies, never by subsequent portfolio returns. Rights issues inherit
the conservative no-participation policy. Merger/delisting requires a separate
verified transfer or cash-settlement path. If essential terms or valuations are
unavailable, the affected run stays `NOT_EVALUABLE`; no security or session is
dropped or given a fabricated price.

Only private, non-commercial use of the existing RQAlpha data is permitted.
Original disclosures and vendor data remain local. Public delivery may contain
code, aggregate results, source links and content hashes, but no restricted raw
bars, account ledgers, holdings or screenshots. The prospective service and
Console V1.5 deployment remain separate and unchanged. CSI500, live brokerage,
additional factor search and automatic strategy deployment are forbidden.
