# V2-010 global ETF USD free source capture

Status: `CAPTURE_COMPLETE_REQUIRES_OFFLINE_NORMALIZATION`.

The constrained capture command retrieved exactly five configured public source
bodies and stored each under its SHA-256 identity. It did not fetch market
prices, access a paid provider, create a credential, run a backtest or modify
formal qualification.

| Item | SHA-256 |
| --- | --- |
| Source-capture receipt | `13232e4abf38082746d0d26678e01cc38b98edad1f355834916610c0f1f28f29` |
| NYSE calendar page | `b7c8c2fa1923de735a0bc29a4697b94957a6cc6ad7e219739282fea871d2de6f` |
| State Street distributions | `99f3d5e8842ad755e98a6d7d379ff3addf7d71f87a8b779b40d420250e60a114` |
| State Street GLD page | `063bffdaf4dfd4fce2c4d847f52afb9d49d1b01d526a965715e6a4461f881fa4` |
| iShares distribution library | `d6439d632f9d33d9440172829898bb3df0bac00ca98ed07f894c5f26dd2ccddf` |
| Invesco ETF tax center | `9d1c6e7aaac750612d111a81806abad6e5e034af560b2a61822ba35800ca1f37` |

The capture is deliberately not a calendar or corporate-action ledger. The
second-layer crosscheck accepts only separately normalized local inputs that
bind their sessions, events and static-universe records to these source hashes.
Until those inputs exist, no Yahoo event or raw session is declared confirmed.
