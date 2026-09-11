# V2 Free Suspension Audit

The CSI300 missing-session gate uses free evidence. BaoStock unadjusted daily
rows provide independent `tradestatus` evidence. SSE and SZSE archived records
may promote an interval to `OFFICIAL_VERIFIED`; AKShare/Eastmoney records remain
discovery-only.

Every missing member session is classified as `PRE_LISTING`, `POST_DELISTING`,
`MARKET_CLOSED`, `BAOSTOCK_SUSPENDED`, `OFFICIAL_SUSPENDED`,
`PROVIDER_CONFLICT`, or `UNEXPLAINED`. Consecutive BaoStock suspension dates are
compressed by the frozen market calendar. Only conflict and unexplained counts
block the missing-session gate.

Tushare is optional and is not part of this gate's required evidence. Network
capture always requires an explicit flag; tests use recorded fixtures only.

Current frozen input contains 15,743 missing member sessions among 852,600
checked CSI300 member-sessions. The free-provider classification has not yet
run, so the gate remains `BLOCKED_DATA`.
