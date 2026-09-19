# EXQ-001 candidate history revalidation

Status: HISTORY_REVALIDATION_NOT_EXECUTION_QUALIFICATION.

Existing reviewed history manifests were filtered to claims intersecting the
275 exact SZSE keys in the user-returned EXQ monthly replay. Only these claims
were revalidated. Original manifest hashes were checked, relevant PDF/catalog
objects copied into separate content-addressed subset manifests, and the
unchanged load_histories validator was run against actual PDF bytes and
freshly extracted text. No source claim or historical report was overwritten.

## Results

| Measure | Count |
| --- | ---: |
| Relevant distinct historical claims | 30 |
| Claims accepted by existing validator | 27 |
| Claims rejected | 3 |
| Unique SZSE keys supported by accepted histories | 210 |
| Remaining SZSE keys without accepted history support | 65 |
| SSE keys outside this revalidation | 3 |

Accepted histories preserve the original exclusive start/cutoff treatment,
publication and signature-date bounds, planned-versus-actual distinction,
issuer/page-anchor checks and monthly resumption checks. A further check used
all 155 hash-verified PDFs in the complete CNINFO discovery inventory with the
existing completed-resumption detector. It did not flag an additional
in-window completed resumption for the accepted claims. This detector check
does not claim exhaustive manual adjudication of every possible contradiction.

Three claims were rejected and retained: one sz000793 claim exceeded the
observed-state cutoff; two sz000540 claims lacked the specified page excerpt.
No validator, threshold or anchor was loosened to accept them. Claim rejection
does not necessarily leave every associated date unsupported, since other
accepted claims may overlap it.

## Remaining keys by issuer

| Symbol | Keys |
| --- | ---: |
| sz000009 | 7 |
| sz000063 | 3 |
| sz000540 | 5 |
| sz000562 | 6 |
| sz000629 | 4 |
| sz000738 | 4 |
| sz000793 | 6 |
| sz002081 | 2 |
| sz002129 | 2 |
| sz002310 | 3 |
| sz002375 | 3 |
| sz002415 | 2 |
| sz002456 | 3 |
| sz002465 | 1 |
| sz002673 | 4 |
| sz300058 | 1 |
| sz300070 | 4 |
| sz300072 | 1 |
| sz300251 | 4 |

## Provenance and claim boundary

Result SHA-256: 620b349f766c7afabeebaaad2ae26911e257215c749154785022f6c2b678ccf2.
Persistent root: artifacts/v2/exq_history_revalidation_20260919/.
The result contains full accepted/rejected claims, exact matched keys, remaining
keys and validator/source hashes. The actual review script and subset inputs
are archived beside it; its /tmp paths describe the original execution workspace.

The PDF inventory used for contradiction checks is
33ce8849b1542fc7c304a04fd18b97a2c38678800171cb130c031a29a58d305a,
persisted under artifacts/v2/exq_cninfo_paginated_20260919/.

This is issuer-history support for retrospective missing-session explanation.
It is not evidence that the information was available at signal T, nor authority
to exclude a signal because of a future missing label. The 65+3 remaining keys
are not a new global free-funnel result: the historical 540-residual funnel and
original EXQ report remain immutable. Corporate-action cash/share accounting,
execution-price evidence and trading-rule qualification remain incomplete.

Candidate qualification, FORMAL_PIT_STATUS and FORMAL_RESEARCH_STATUS remain
BLOCKED_DATA; CSI500 remains NOT_STARTED. No training or backtest was run.
