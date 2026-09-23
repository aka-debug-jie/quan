# CN Research Closure Next: bounded event evidence

Status: `RETROSPECTIVE_ACCOUNTING_EVIDENCE`. This file summarizes why the
versioned overlay exists; the field-level authority, document URLs, retrieval
times, page references and SHA-256 values are in
`configs/closure/action_evidence_v1.yaml` through `action_evidence_v4.yaml`.
Original PDFs and HTTP headers are held only in the ignored local evidence
archive. No raw market data, account ledger or screenshot is redistributed.

| Held-event key | Issuer action | Record date | Offered shares / old share | Subscription price (CNY) | New shares listed | Actual issued shares |
| --- | --- | --- | ---: | ---: | --- | ---: |
| sh601012 / 2019-04-17 | rights issue | 2019-04-08 | 0.30 | 4.65 | 2019-04-29 | 833,419,462 |
| sz000686 / 2016-04-15 | rights issue | 2016-04-06 | 0.20 | 9.08 | 2016-04-22 | 383,286,883 |
| sz002673 / 2017-04-11 | rights issue | 2017-03-29 | 0.26 | 6.87 | 2017-04-20 | 706,270,150 |
| sz002017 / 2019-02-28 | rights issue | 2019-02-19 | 0.30 | 4.04 | 2019-03-13 | 100,160,748 |
| sh601162 / 2020-03-19 | rights issue | 2020-03-10 | 0.30 | 3.60 | 2020-03-31 | 1,485,967,280 |
| sh600030 / 2022-01-27 | rights issue | 2022-01-18 | 0.15 | 14.43 | 2022-02-15 | 1,552,021,645 |
| sh600089 / 2017-06-09 | rights issue | 2017-05-31 | 0.156269 | 7.17 | 2017-06-22 | 480,765,103 |
| sz002074 / 2017-11-27 | rights issue | 2017-11-16 | 0.30 | 13.69 | 2017-12-05 | 260,230,819 |

The offered ratio is not automatically the ratio actually subscribed by all
shareholders. Source documents retain both the record share count and actual
issued count. Under the inherited research policy, the simulated account does
not subscribe and receives neither new shares nor synthetic cash. These
documents verify the event and accounting classification after the fact;
they do not alter T-date factors, ranking, membership or historical raw bars.

The original five blocking keys and their run/benchmark dependencies are in
the content-addressed graph `2f94f1d1194ccc9b5acc1ae1f8f0d78224565acd4ac71e3331bd581c346ffb2c`.
The first complete closure revision preserved a second graph
`207a10eca3b8c2506b5205c6b9c3e36a1d6ac8f3fbc37dae8a0faa31dcf25a18`:
it exposed later B100, conditional-reversal and diagnostic-control rights
issues, rather than treating the first unblocked date as a full-period pass.
The `sz002074` filing was added after a no-return scan of the frozen
conditional-reversal target schedule marked it as a *possible* later dependency;
only a complete account run can establish whether it is actually held.

`sh600832 / 2015-05-20` remains separate. An archived SSE notice confirms
delisting on that date (SHA-256
`1480b3b3a229c53d10d727cc06bd1a677a57ceb857cf3facfae2e25fc7a5654f`),
and the successor issuer's annual report confirms a 3.05:1 conversion to
`sh600637` (SHA-256
`152dfcfb31044da528c6f080f5e21c1ccb7122013a6f0a33bb9f8296bfae36d0`).
The merger terms refer fractional entitlements to ChinaClear processing;
the [original merger filing](https://static.cninfo.com.cn/finalpage/2014-11-22/1200409876.PDF)
(page 60, SHA-256
`f9bbdb2bc7aaae4d304a948c6ae2c18a4d977adb9dbd5f8d717a5885c425584c`)
does not disclose the paper account's final allotment. Therefore
the present data does not identify the paper account's exact rounded allotment
or a complete entitlement/transfer valuation path. The affected runs therefore
remain `NOT_EVALUABLE` until a separately verified account treatment exists.

All economic evaluation in this round remains final-revised, single-vendor,
fully touched retrospective private non-commercial research. The independent
account check verifies fills and NAV from order intents; it does not certify
the vendor's corporate-action source or historical PIT status.
