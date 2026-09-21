# CN Historical Research V3 data preflight

Status: `REAL_DATA_PREFLIGHT_COMPLETE_BEFORE_PORTFOLIO_RETURNS`.

- RQAlpha object: fixed HTTPS `rqbundle_202609.tar.bz2`.
- Bundle SHA-256: `80e1d3287ec2f9f3c255fe648c5487bc4cf5e4186a1dbdb0659939ba7e931139`.
- Safe extraction tree: `9175506046669b3168003cabd0313fed501d1f9ca4906d7cc083809ae79f2620`.
- Source calendar: 5,587 sessions, 2005-01-04 through 2027-12-31; the V3 protocol uses only 2015-01-05 through 2025-12-31.
- Source stock store: 5,525 symbols with raw OHLC, previous close, volume, turnover, and upper/lower limits.
- Source event/status stores: 5,889 dividend symbols, 4,987 split symbols, 6,456 factor symbols, 3,452 suspension symbols, and 5,574 ST status keys.
- Normalized bars SHA-256: `98ee7b8defbc5c14bb2e120b782570ca60484a96d056e5c07a389f5a740c5432`.
- Normalized coverage: 10,938,536 rows, 5,419 symbols, 2014-10-09 through 2025-12-31, with no nonpositive OHLCV rows dropped.
- Frozen scoring coverage before portfolio evaluation: 2,674 sessions and exactly 300 securities per session. The final score artifact identity is recorded by the protocol-freeze commit's generated preflight manifest.

The vendor archive is final-revised history and is allowed only for private,
non-commercial, non-redistributed historical research. It is not official PIT
evidence and does not reopen EXQ-001 or authorize BT-001. No CSI500 file, label,
or result was read.
