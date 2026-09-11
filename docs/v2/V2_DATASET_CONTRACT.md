# Quant V2 Dataset Contract

Every external dataset has a strict YAML registry containing a GitHub repository,
40-character commit, release or commit-snapshot identity, code license, market
data rights status, artifact hashes, coverage, adjustment semantics, historical
membership status and allowed/forbidden uses.

Usage levels are `FIXTURE_ONLY`, `RESEARCH_ADJUSTED_ONLY`, `BACKTEST_RESEARCH`,
`EXECUTION_QUALIFIED` and `PROSPECTIVE`. A level is a ceiling, not proof that the
current local capture is qualified. Missing bytes, hashes, coverage or semantics
fail closed. `RESEARCH_ADJUSTED_ONLY` cannot supply execution prices.

Unreviewed market-data rights prohibit redistribution. Repository code licenses
do not imply rights to republish bundled market data. External retrospective
datasets cannot support a fresh-holdout claim or live order.

Captured files live under ignored `data/external/<dataset-id>/<sha256>/` paths.
The capture interface accepts HTTPS GitHub URLs only, requires an expected hash,
uses bounded retries and publishes content-addressed bytes plus a deterministic
receipt. Changed upstream content creates a distinct path and cannot overwrite
an existing snapshot.
