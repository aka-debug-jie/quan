# SSE residual delisting audit

Five SSE notices were downloaded with explicit network authorization. Original
response bytes, HTTP headers, final URL, retrieval timestamp and SHA-256 are in
the ignored local `artifacts/v2/delisting_evidence` archive. The manifest is
`45050aa72929b343813030341b444889b9eae7ca324882ec48d96b99b18f0216`.

Dates independently parsed from the original notices:

| Symbol | Delisting effective date |
| --- | --- |
| 600005 | 2017-02-14 |
| 600832 | 2015-05-20 |
| 600837 | 2025-03-04 |
| 601299 | 2015-05-20 |
| 601989 | 2025-09-05 |

POST_DELISTING takes precedence starting on the effective date, inclusive,
including dates previously covered by an exchange suspension record. Original
member intervals and the previous suspension report are not rewritten.

The five supplied candidate intervals extend beyond delisting. This is recorded
separately as a membership anomaly, not repaired by deleting observations or
substituting the absorbing company's prices.

CSI300 adjustment dates remain UNVERIFIED for all five names. Bounded searches
of csindex.com.cn did not retrieve the needed original adjustment notices.
The SSE/CSI joint 2015-05-14 notice at
https://www.sse.com.cn/market/sseindex/diclosure/c/c_20150911_3985142.shtml
concerns SSE index changes; it does not establish the CSI300 change date.
Do not substitute a delisting date or a semiannual rebalance for missing CSI
evidence. Membership qualification remains BLOCKED_DATA even if the SSE gap
classification passes.

Run `sudo bash scripts/v2/reclassify_sse_delisting.sh` to verify archived hashes
and independently reparse original dates before writing a new sealed report.
This step is offline. Host-side execution is required because the development
user cannot read the sealed source report. No real-data counts are claimed until
that command completes.
