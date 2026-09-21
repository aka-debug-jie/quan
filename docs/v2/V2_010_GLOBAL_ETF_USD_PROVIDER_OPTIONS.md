# V2-010 global ETF USD provider options

Status: `FREE_RESEARCH_AUDIT_SELECTED`; formal external qualification remains
`PENDING_SOURCE_APPROVAL`.

This is a read-only feasibility comparison for the seven frozen US-listed ETF
symbols. It neither approves a source nor creates an account, API key, market
data download, model run or backtest.

## Recommendation

Do not purchase a provider at this stage. First run a zero-cost,
non-promoting research audit from the already archived Yahoo raw responses,
official ETF-issuer distribution records, and an official US exchange calendar.
It can establish whether the frozen seven-symbol universe is internally
reproducible and where provider observations disagree with issuer records.

This path remains research-only. The existing Yahoo ingestion is explicitly
`RESEARCH_ADJUSTED_ONLY`; raw fields observed in the archived response cannot
be relabelled as execution prices or used to pass V2-010.

## Alternatives considered

| Source | Role | Boundary |
| --- | --- | --- |
| Existing Yahoo raw-response archive | Free primary research observation | Provider observation only; never execution qualification. |
| ETF issuer distribution pages | Free corporate-action crosscheck | Must be captured and hash-bound per issuer; no inferred missing dates. |
| HF Data Library GitHub/Zenodo project | Optional free OHLCV crosscheck | Post-2022 data are IEX-only, so it is not a full-market execution source. |
| EODHD | Later formal-provider candidate | Full history requires a paid plan; defer unless the free audit proves insufficient. |
| Polygon / Tiingo | Later alternatives | Require separate entitlement and data-use review. |

## Evidence boundary after provider selection

The provider can supply only part of V2-010. The qualification remains blocked
until all of the following are captured and hash-verified:

1. immutable raw OHLCV and corporate-action manifests for the frozen seven ETF symbols;
2. a local exchange calendar from an official source;
3. a frozen static-universe and listing/inception evidence record;
4. a project-owned USD cost-model contract; and
5. a deterministic reproduction receipt.

No field from an adjusted series may become an execution price. No free audit
or provider choice authorizes a broker connection, real order, BT-001 or a
profitability claim.

## Official references

- [EODHD historical EOD data](https://eodhd.com/financial-apis/api-for-historical-data-and-volumes)
- [EODHD corporate actions](https://eodhd.com/financial-apis/api-splits-dividends)
- [EODHD public pricing](https://eodhd.com/commercial-pricing)
- [Alpha Vantage daily-data entitlement](https://www.alphavantage.co/documentation/)
- [HF Data Library provenance and licence](https://github.com/elkassabgi/hfdatalibrary)
- [Polygon stocks data and plans](https://polygon.io/stocks)
- [Tiingo EOD fields](https://www.tiingo.com/documentation/end-of-day)
- [Tiingo ETF distributions](https://www.tiingo.com/documentation/corporate-actions/dividends)
