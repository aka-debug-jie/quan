# Risk Contract

V1 permits only long ETF positions, target weights from 0 to 1, no shorting, and
leverage fixed at 1. Portfolio-level position caps, cash floors, concentration
limits, stale-data gates, and turnover controls must be configured before a
paper strategy can be promoted.

The system must halt signal promotion when data is stale, incomplete, fails
schema validation, or cannot be reconciled to its manifest. Backtest output is
research evidence, not a promise of return or authorization to trade.

M0 cannot contact a broker or send a real order.
