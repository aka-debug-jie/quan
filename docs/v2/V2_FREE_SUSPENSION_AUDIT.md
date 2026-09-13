# V2 Free Suspension Audit

Status as of 2026-09-13: **CLOSED_ACCEPTED_WITH_DOCUMENTED_LIMITATIONS**.
The user accepted stage closure and explicitly directed us not to spend more
time chasing the remaining sub-1% SZSE residual. The free audit is complete
as a delivery task: 8,030/8,093 SZSE days explained, 63 retained as unknown,
zero conflicts; SSE residual zero. No further announcement collection,
Hongyuan CSI-date search, full-PIT audit, or sudo replay is scheduled for
this task. Historical machine gates remain factual and unchanged.
See [closure record](FREE_AUDIT_CLOSURE_20260913.md) for the accepted final state;
the sections below preserve the earlier audit contract and evidence history.

## Scope and gates

Audit missing CSI300 member sessions using free, immutable evidence. Do not buy
data, require Tushare, train research models, rewrite the frozen price or member
inputs, or widen permissions on `/srv/quant-v2/sealed_holdout`. The development
user prepares fixed scripts; the user runs sealed evaluation as sudo/quant-eval.
BaoStock login attempts were stopped after timeout and must not be retried in
this run without a new reason.

The missing-session explanation gate and PIT membership gate are independent.
A retrospective explanation never establishes that a security was a valid
point-in-time index member, nor that the evidence was available historically.
SSE/SZSE index announcements must not be substituted for CSI300 adjustments.

## Evidence levels

- BaoStock unadjusted daily rows can provide independent `tradestatus` evidence
  when available. The baseline provider classifier is unchanged.
- Hash-verified exchange records can support `OFFICIAL_SUSPENDED` and an
  `OFFICIAL_VERIFIED` exchange interval. Full-session timing must be established.
- The separately scoped `SZSE_MONTHLY_PLUS_ISSUER_NOTICES_RETROSPECTIVE` report
  may add `ISSUER_CONFIRMED_SUSPENDED` from manually reviewed issuer disclosures
  archived from official CNINFO/SZSE hosts. The primary retrospective document
  must be published after its explicitly confirmed resumption date; a scheduled
  resumption announcement alone is not proof of execution. The original monthly
  report remains immutable.
- Each issuer claim binds raw PDF hashes, official URLs, security identity,
  exact dates, page numbers and original text anchors. Different start or
  identity documents require matching issuer names and security codes. A
  withdrawn/cancelled document is not admitted. Catalogue search results and
  announcement lists alone do not establish an actual resumption.
- AKShare/Eastmoney records, fund reports, third-party quotations, adviser-only
  statements and planned resumption dates remain discovery/corroboration only
  under the currently implemented supplement rules. They are not relabelled as
  issuer confirmation.
- A notice explicitly confirming continuing suspension could establish a
  right-censored historical interval, but this subtype is not implemented or
  admitted to a gate by the current actual-resumption verifier. It remains a
  separate research lead, not an excuse to extend open monthly evidence.

## Date and classification rules

The baseline free-provider report classifies sessions as `PRE_LISTING`,
`POST_DELISTING`, `MARKET_CLOSED`, `BAOSTOCK_SUSPENDED`, `OFFICIAL_SUSPENDED`,
`PROVIDER_CONFLICT`, or `UNEXPLAINED`. Calendar compression uses the frozen
market calendar. These public types are unchanged by the independent supplement.

SZSE monthly open records (`9999/12/31`) are capped to their own calendar month.
Intraday starting sessions and actual resumption dates cannot explain a full
missing day. The issuer supplement conservatively excludes the start date and
resumption date, adds only to prior `UNEXPLAINED` rows, and preserves or adds
conflicts. It does not silently override a conflicting monthly record.

Every output must account for the exact original missing-date set without
omissions or duplicates, and recompute covered, residual, conflict and interval
counts. Original `membership_gate` is retained. The baseline global dataset gate
is not promoted merely because a separately scoped exchange/supplement gate
passes.

## Capture and execution

Network capture requires an explicit allow-network option for uncached requests;
offline evaluation never opens a connection. Preserve request parameters,
response bytes, official URLs, retrieval times and content hashes. Current
CNINFO catalogue org IDs are request identifiers only, not historical universe
or PIT membership evidence. Tests use fixtures; sealed execution is user-run.

The full reduced evidence queue contains only security/date envelopes/counts,
not raw prices. Envelopes are search ranges, not proof of uninterrupted missing
or suspended sessions. Raw and derived artifacts are additive and content
addressed; withdrawn and rejected files may be retained as discovery evidence
but are not admitted to classification.

## Recorded progress

The frozen input contains 15,743 missing member sessions among 852,600 checked
CSI300 member-sessions. In user-returned batch 4, SZSE has 4,172 explained and
3,921 residual sessions out of 8,093, with zero conflicts. Both its gap gate and
PIT membership gate remain `BLOCKED_DATA`. This is a dated checkpoint, not an
automatic global qualification. See `SZSE_MONTHLY_SUSPENSION_AUDIT.md` and the
immutable run receipts for later checkpoints and source limitations.
