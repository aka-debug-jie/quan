# Quant V2 Experiment Contract

V2 experiments use chronological development, validation, external retrospective
test and prospective paper stages. Random splits are forbidden. A future-20-day
label requires a 20-session purge and embargo.

Every attempt records experiment and strategy family IDs, parameters, dataset
and split hashes, code commit, result and the preregistered reason for any next
experiment. Failed and rejected trials are retained. Parameter grids and seeds
must be frozen before external test access.

Reported evidence includes signal IC/Rank IC/ICIR and decay where applicable;
portfolio return, volatility, Sharpe, Sortino, drawdown, Calmar, turnover, costs,
time in market and benchmark-relative measures; and prespecified cost, delay,
parameter, missing-data, date and crisis stresses.

Promotion states are `REJECTED_NO_EDGE`, `RESEARCH_CANDIDATE`,
`EXTERNAL_REPLICATION_PASS` and `PAPER_CANDIDATE`. No state authorizes live
trading. Strategy implementation begins only after dataset qualification work
is separately accepted.
