# EXQ-001 equity-distribution date candidates

Status: DATE_AND_CASH_TEXT_EXTRACTED_NOT_LEDGER_VALIDATED.

Six archived issuer PDFs explicitly state a cash distribution term, a record
date and an ex-right/ex-dividend date. Each PDF body was SHA-256 verified
before extraction. Cash shown below is the gross announced term per ten shares,
not an investor-specific after-tax amount.

| Symbol | Record date | Ex date | Gross cash per 10 shares | Residual-date relation |
| --- | --- | --- | --- | --- |
| sz000009 | 2015-08-05 | 2015-08-06 | 0.20 CNY | Ex date is inside residual interval |
| sz002001 | 2015-06-17 | 2015-06-18 | 3.50 CNY | Before residual interval |
| sz002081 | 2015-06-02 | 2015-06-03 | 1.00 CNY | Ex date is inside residual interval |
| sz002310 | 2019-08-16 | 2019-08-19 | 0.94 CNY | After residual interval |
| sz002400 | 2015-05-14 | 2015-05-15 | 1.10 CNY | Before residual interval |
| sz300251 | 2016-05-20 | 2016-05-23 | 1.00 CNY | Ex date is inside residual interval |

The dates and cash text are candidate fields from official implementation
notices, not ledger entries. They have not been reconciled with Qlib factor
changes, raw execution prices, share conversion terms, tax treatment or each
event's exact candidate dependency role. In particular, the three in-interval
events must be reconciled before their price-factor impact can be asserted.

No price series, factor, label or session classification changes in this
update. Candidate qualification, formal PIT and formal research remain
BLOCKED_DATA; CSI500 remains NOT_STARTED.
