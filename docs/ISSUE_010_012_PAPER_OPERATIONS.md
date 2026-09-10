# Issue 010–012 Paper Operations

The local paper account starts with CNY 100,000 and zero holdings. It records
Decimal fractional ETF shares, raw-reference and impacted fill prices, fees,
cash distributions, share splits, raw-close NAV and append-only ledger hashes.
It contains no credentials or broker transport.

`quant paper initialize` creates the strategy and equal-weight benchmark
accounts. `quant paper run-daily --allow-network` refreshes the approved raw
provider histories, validates the local inputs, processes all pending paper
sessions, writes a hash-linked account state and creates an offline HTML report.
`quant paper reconcile` replays the ledger before reporting its state.

The strategy remains experimental because Issue 009 concluded
`NO_EVIDENCE_OF_EDGE`. The paper account must not be treated as a return claim
or a live-trading authorization.

Cash distributions require a verified `payment_date` once an account holds the
asset on its record date. A missing date, a failed raw refresh, missing coverage,
invalid evidence or an incomplete causal input creates a failure receipt and
prevents fills and new orders for that run.

The optional user-level systemd timer runs at 16:20 Asia/Shanghai on weekdays,
is persistent across missed timer activations and writes journal plus desktop
notifications on failure. Install it only after reviewing
`systemd/paper.env.example`; the environment file explicitly enables automatic
network data retrieval.
