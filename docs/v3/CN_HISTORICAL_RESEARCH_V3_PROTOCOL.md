# CN Historical Research V3 protocol

Status: `PREREGISTERED_BEFORE_PORTFOLIO_RETURNS`.

This is a separate `HISTORICAL_RESEARCH_ONLY` comparison. It does not amend
EXQ-001, BT-001, the V2 no-qualification closure, CSI500 sealing, or the running
prospective account. The machine-readable authority is
`configs/v3/cn_historical_research_v3.yaml`.

The frozen evaluation window is 2015-01-05 through 2025-12-31. The daily
universe is the 300 most liquid eligible Shanghai/Shenzhen common stocks using
only information available by each signal close. It is not called historical
CSI300. The seven AF-003 factor definitions and equal daily cross-sectional
z-score are retained; no new factor or learned model is allowed.

Signals use the T close and execute no earlier than a later session open. Raw
prices drive fills and marks; causally adjusted histories drive factors. The
six main configurations, four stress tests, CNY 1,000,000 research capital,
lot rules, costs, liquidity cap, labels, and failure policy are frozen in the
config before portfolio returns are read.

RQAlpha monthly data may be used only for private non-commercial historical
research and may not be redistributed. It is final-revised vendor history, not
strict point-in-time official evidence. A missing held valuation, unexplained
corporate action, unresolved delisting, or material independent-source conflict
makes the affected result not evaluable instead of assigning a zero return.

The first real run is the simple B00 benchmark. Only after its buys, first
two-sided rebalance, cash, corporate actions, and NAV are independently checked
may the fixed AF-003 matrix run. Negative returns are retained. Completion of
this protocol never authorizes paper deployment or live trading.
