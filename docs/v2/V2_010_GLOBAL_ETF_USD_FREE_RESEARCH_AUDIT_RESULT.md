# V2-010 global ETF USD free research audit result

Status: `FREE_RESEARCH_ARCHIVE_VALIDATED_NOT_EXECUTION_QUALIFIED`.

The new offline audit verified the frozen Yahoo report and every referenced raw
response by SHA-256. It reports metadata and coverage only; no OHLCV values
were exported and no provider request was made.

| Item | SHA-256 |
| --- | --- |
| Frozen Yahoo report bytes | `c24b0a11bf99e406c5b03dc3c26eebac5a51599834f55d27fff1511c51c8ab0a` |
| Free research audit receipt | `cf3d548bd5dd7db0e6f7ef661fc10d97f45904a5dbf92065b5c8f7f06de674f7` |

| Symbol | Complete raw OHLCV sessions | First session | Last session | Yahoo event observations |
| --- | ---: | --- | --- | ---: |
| BIL | 4,852 | 2007-05-30 | 2026-09-10 | 128 |
| DBC | 5,181 | 2006-02-06 | 2026-09-10 | 9 |
| EFA | 6,296 | 2001-08-27 | 2026-09-10 | 48 |
| GLD | 5,486 | 2004-11-18 | 2026-09-10 | 0 |
| IEF | 6,068 | 2002-07-30 | 2026-09-10 | 290 |
| MCHI | 3,884 | 2011-03-31 | 2026-09-10 | 31 |
| SPY | 8,461 | 1993-01-29 | 2026-09-10 | 135 |

The audit intentionally leaves issuer-action and official-calendar crosschecks
as `NOT_PROVIDED`. Yahoo observations cannot be relabelled as execution prices,
and this receipt does not change formal PIT, formal research, CSI500, BT-001 or
paper-account eligibility.
