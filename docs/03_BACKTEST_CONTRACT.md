# Backtest Contract

- A close-derived signal on T cannot fill on T. The earliest permitted fill is
  a later exchange-local trading date.
- V1 is long-only, unlevered, and fully deterministic for a fixed data snapshot,
  configuration, and seed.
- Commission rate, minimum commission, spread, and slippage are mandatory
  configuration fields. A run missing any field is invalid.
- Orders must have deterministic identifiers so reruns cannot duplicate an
  intended paper order.
- Benchmarks and assets follow the same calendar and return conventions.
- Future implementations must define suspension, limit-up/limit-down, missing
  price, cash, rounding, dividend, and split behavior before reporting results.

M0 provides timing and configuration invariants only. No backtest engine or
performance calculation is implemented.
