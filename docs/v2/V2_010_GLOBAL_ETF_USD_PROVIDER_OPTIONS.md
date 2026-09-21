# V2-010 global ETF USD provider options

Status: `PENDING_USER_ACCOUNT_AND_LICENSE_ACCEPTANCE`.

This is a read-only feasibility comparison for the seven frozen US-listed ETF
symbols. It neither approves a source nor creates an account, API key, market
data download, model run or backtest.

## Recommendation

Use EODHD's **EOD Historical Data -- All World** plan as the first provider
candidate, subject to the account holder accepting its applicable data-use
terms. Its official documentation describes raw OHLCV, adjusted close and
volume for ETFs, and separate split/dividend histories with declaration,
record, ex and payment dates. The provider's public page listed a personal-use
price of USD 19.99 per month and 30+ years of history when assessed on
2026-09-21. Reconfirm price and permitted use before purchase.

The free EODHD tier is not suitable: it is limited to the past year and 20 API
calls per day. The existing Yahoo snapshots remain `RESEARCH_ADJUSTED_ONLY` and
are not a substitute for this source.

## Alternatives considered

| Provider | Fit | Reason not selected first |
| --- | --- | --- |
| EODHD | Best first candidate for EOD qualification | Requires a user account and a review of applicable data-use terms. |
| Polygon | Strong US consolidated-market alternative | Its public 10-year individual plan is insufficient for a long historical study; 20+ year access is on a higher tier. |
| Tiingo | Technically promising alternative | It exposes raw and adjusted EOD fields, but detailed ETF distribution access is described as beta/enterprise-gated, so entitlement must be confirmed first. |

## Evidence boundary after provider selection

The provider can supply only part of V2-010. The qualification remains blocked
until all of the following are captured and hash-verified:

1. immutable raw OHLCV and corporate-action manifests for the frozen seven ETF symbols;
2. a local exchange calendar from an official source;
3. a frozen static-universe and listing/inception evidence record;
4. a project-owned USD cost-model contract; and
5. a deterministic reproduction receipt.

No field from an adjusted series may become an execution price. No provider
choice authorizes a broker connection, real order, BT-001 or a profitability
claim.

## Official references

- [EODHD historical EOD data](https://eodhd.com/financial-apis/api-for-historical-data-and-volumes)
- [EODHD corporate actions](https://eodhd.com/financial-apis/api-splits-dividends)
- [EODHD public pricing](https://eodhd.com/commercial-pricing)
- [Polygon stocks data and plans](https://polygon.io/stocks)
- [Tiingo EOD fields](https://www.tiingo.com/documentation/end-of-day)
- [Tiingo ETF distributions](https://www.tiingo.com/documentation/corporate-actions/dividends)
