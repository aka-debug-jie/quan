# Quant V2 Research Charter

Status: `FROZEN_BEFORE_V2_DATA_CAPTURE`

Quant V2 is an isolated multi-dataset research factory. It may develop
cross-asset ETF, A-share cross-sectional factor and incremental ML hypotheses,
then retain at most two paper candidates. A valid negative result is expected
and must remain in the registry.

V2 does not modify V1 strategy code, accounts, paper databases, contracts,
Issue 009 evidence or the 2026-10 through 2028-03 prospective observation.
Historical external data is labelled `PROJECT_FRESH_EXTERNAL_RETROSPECTIVE`;
it is never described as future prospective evidence.

Every experiment must bind dataset, split, code and configuration hashes;
preserve all trials; use chronological evaluation; include costs; execute a
T-close signal no earlier than T+1; and forbid leverage, shorts and live orders.
The highest V2 promotion state is `PAPER_CANDIDATE`.

V2-000 and V2-001 define contracts and registry interfaces only. They do not
download a market archive, create a strategy, run a backtest or open a V2 paper
account.
