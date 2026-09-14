# Free Evidence Final Funnel Replay

Status: `CLOSED_WITH_RESIDUAL`; `FREE_EVIDENCE_RESIDUAL`; `gap_gate=INCOMPLETE`.

The frozen Qlib audit contains 15,743 authoritative missing sessions. Two
restricted, offline replays of identical audit, calendar, SSE and SZSE inputs
produced identical canonical outputs.

| Final class | Sessions |
| --- | ---: |
| PRE_LISTING | 0 |
| POST_DELISTING | 0 |
| MARKET_CLOSED | 0 |
| OFFICIAL_SUSPENDED | 15,203 |
| INDEPENDENT_PROVIDER_CONFIRMED | 0 |
| PROVIDER_CONFLICT | 0 |
| UNEXPLAINED | 540 |

The counts sum to 15,743. Every input `symbol + expected_session` has one
classification. Deterministic reconstruction produced 724 intervals. Residual
contains the 540 unexplained sessions only; provider conflicts are zero.

Inputs: audit `99013d70b4ab14d76c9fd1e511edfac9418cfb6ca113474de1cab654f1f57c02`,
calendar `aa25005ca6d283fe9ffcc518af74cd8799d94102d64f22982977cf695366b2c9`,
SSE `c73fef79bde394f0fcbd1b667237e3b76ae77c17c26ebddfc1da7e9941337e97`,
SZSE `758c6cfed64d640ccdd1ba1c4b34269052b8a0ce952ac33e12d36a6148ad3164`.

Reproducibility hashes: sessions `29039f21a0f30b6db6e5028927a6194b9942be8c83105ca7a28a5ac924733c68`,
intervals `6342713499912cc952db35a8ffeb61b0fc8310a5c8cf98246558817c99332d06`,
residual `5402dea11a1a430a1807edfd53a986ee8711f89797ff27deb0be7914cfe0cafb`,
funnel `20a61fc923cce2b9dd46238e0c0d78801886e0b063061c30339f6c839154247b`.

Machine artifacts are under
`/srv/quant-v2/sealed_holdout/artifacts/v2/free_evidence_funnel/` in
content-addressed `sessions`, `intervals`, `residual`, and `funnel` directories.

`FORMAL_PIT_STATUS=BLOCKED_DATA` and
`FORMAL_RESEARCH_STATUS=BLOCKED_DATA` remain unchanged. This free evidence
funnel does not certify PIT membership or formal research readiness.

The 540 residuals are frozen as this route's negative result. They are not a
standing data-archaeology queue and may be reconsidered only when a separately
approved formal candidate specifically depends on one of their securities or
dates.
