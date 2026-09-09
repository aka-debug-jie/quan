# Data Contract

## Raw inputs

Raw provider exports are immutable and content-addressed with SHA-256.
Repeating the same request with identical bytes is idempotent; attempting to
replace an existing path with different bytes fails. AKShare exposes a DataFrame,
not raw HTTP response bytes, so the retained raw artifact is precisely named a
provider-export CSV and keeps the provider's Chinese columns unchanged.

Each normalized Parquet artifact has a separate SHA-256 and an immutable
manifest recording provider, adapter version, request, price basis, raw and
normalized hashes, date coverage, row count, and calendar fingerprint.
Generated and large datasets stay outside Git, while manifests schemas, hashes,
calendar configurations, and small synthetic fixtures may be committed.

## Daily bar schema

Each observation has `symbol`, `exchange`, `price_basis`, exchange-local
`trading_date`, positive `open`, `high`, `low`, and `close`, and non-negative
`volume`. High must be at least open and close; low must be at most open and
close. `(exchange, symbol, price_basis, trading_date)` is unique.

Provider fields must later be mapped into this schema by an adapter. Missing
dates, corporate actions, listing status, suspension policy, and universe
membership must be explicit before production research begins. Raw and front-
adjusted ETF series are retained separately; only raw prices may later support
execution auditing.

## Documented non-trading events

An exchange session may be absent only when the instrument configuration names
the date, an explanatory reason, and a content-addressed primary-source
document. The evidence body must be retained under
`data/raw/non_trading_evidence/` and match its configured SHA-256 before a
coverage report may recognize the exception. This records an absence; it never
creates, carries forward, interpolates, or otherwise synthesizes an OHLC bar.

Unexplained absent sessions remain `expected_session_missing` and block research
promotion. A provider bar on a declared non-trading date is an evidence conflict
and also blocks promotion.
