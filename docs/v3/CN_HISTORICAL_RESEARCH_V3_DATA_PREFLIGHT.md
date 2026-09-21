# CN Historical Research V3 data preflight

Status: `REAL_DATA_PREFLIGHT_COMPLETE_BEFORE_PORTFOLIO_RETURNS`.

- RQAlpha object: fixed HTTPS `rqbundle_202609.tar.bz2`.
- Bundle SHA-256: `80e1d3287ec2f9f3c255fe648c5487bc4cf5e4186a1dbdb0659939ba7e931139`.
- Safe extraction tree: `9175506046669b3168003cabd0313fed501d1f9ca4906d7cc083809ae79f2620`.
- Source calendar: 5,587 sessions, 2005-01-04 through 2027-12-31; the V3 protocol uses only 2015-01-05 through 2025-12-31.
- Source stock store: 5,525 symbols with raw OHLC, previous close, volume, turnover, and upper/lower limits.
- Source event/status stores: 5,889 dividend symbols, 4,987 split symbols, 6,456 factor symbols, 3,452 suspension symbols, and 5,574 ST status keys.
- Normalized bars SHA-256: `d0b4f72f8bc95539582f129ed1ad1e9c22c4dbb49f98413566bec9c1e5a3cc8f`.
- Normalized coverage: 10,932,892 rows, 5,419 common-stock symbols, 2014-10-09 through 2025-12-31, with no nonpositive OHLCV rows dropped. Ordinary 302/689 successors are retained, non-stock 990 prefixes are excluded, and code-change/board-switch successors are masked before their effective dates.
- Frozen scoring coverage before portfolio evaluation: 2,674 sessions and exactly 300 securities per session. The final score artifact identity is recorded by the protocol-freeze commit's generated preflight manifest.
- Of 34,760 common-stock adjustment-factor events in the evaluation window, 91 do not share an effective date with a cash-distribution or split record. The runner fails closed if a portfolio actually holds an affected symbol on such a date; it does not manufacture an entitlement.
- The fixed 36-key BaoStock cross-check made two bounded attempts. The provider process produced no response rows and was terminated after the bounded timeout; no third provider was added. Data use therefore remains single-vendor historical research rather than independently cross-checked history.
- The first B00 attempt stopped before completion on `sh601099@2016-01-25`. SSE/CNInfo evidence identifies the unmatched factor change as a 10-for-3 rights issue at CNY 4.24, record date 2016-01-14 and new-share listing 2016-02-02. V3 freezes a no-participation policy: no synthetic cash or shares are credited, and the raw ex-right price remains the portfolio mark. Evidence SHA-256 is `8827f8cf453207478d7a07a6d5ae8b7380fbbce8c8527c485f3367f8bccf1bf2`.
- The next B00 attempt stopped on `sz002466@2017-12-26`, also an evidenced rights issue. The same no-participation rule is bound to its 2017 event (CNY 11.06, 10-for-1.5; evidence `4663d042…b2b23`) and the already published 2019 event (CNY 8.75, actual ratio 0.2934456; evidence `543774ba…6375c`). No other unmatched factor event is exempted.

The vendor archive is final-revised history and is allowed only for private,
non-commercial, non-redistributed historical research. It is not official PIT
evidence and does not reopen EXQ-001 or authorize BT-001. No CSI500 file, label,
or result was read.
