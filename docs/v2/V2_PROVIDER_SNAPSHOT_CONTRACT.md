# V2 Provider Snapshot Contract

Yahoo ETF responses are volatile provider snapshots, not GitHub Release artifacts.
They therefore use a separate contract: explicit network authorization; a canonical
request; raw response bytes; response hash; retrieval timestamp; HTTP metadata;
adapter version; and a content-addressed normalized artifact and manifest.

The fixed V2-005 universe is `MCHI`, `SPY`, `EFA`, `IEF`, `GLD`, `DBC` and `BIL`.
Every stored series is labelled `RESEARCH_ADJUSTED_ONLY`. It may support feature and
regime research, but may not supply execution prices, order audit, Paper Broker data,
execution qualification or a profitability claim. Yahoo dividend and split objects are
stored only as provider observations, not as a corporate-action ledger.
