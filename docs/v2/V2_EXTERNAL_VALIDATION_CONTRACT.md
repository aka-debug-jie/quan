# V2 External Validation and Promotion Contract

V2-010 maintains independent CNY/CSI500 and USD/global-ETF qualification
records. Both require source approval, immutable raw manifests, local calendars,
corporate-action evidence, PIT membership, a frozen cost model and deterministic
reproduction. Yahoo adjusted-price research snapshots do not satisfy any raw
execution requirement.

V2-011 uses LEAN only as a pinned fixture engine. The project and LEAN must
produce exactly the same normalized orders, fills, cash, positions, fees, NAV
and drawdown from a synthetic fixture. Any first difference blocks promotion.

V2-012 can select at most two strategies only after all qualification, external
test, reproduction and engine gates pass. Their cost-adjusted net return and
Sharpe must exceed the same-cost benchmark, while maximum drawdown may not be
more than five percentage points worse. These are paper candidates, never live
trading authorization.

V2-013 has a separate `artifacts/v2/paper` namespace. It is created only for a
selected candidate and only from V2-qualified raw inputs. CNY and USD ledgers
are never combined. V2-014 may create immutable text proposals only; it has no
network, raw-data, sealed-data, training, backtest, promotion, account or V1
capability.
