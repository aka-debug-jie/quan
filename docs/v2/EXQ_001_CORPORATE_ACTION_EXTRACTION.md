# EXQ-001 corporate-action candidate-field extraction

Status: CANDIDATE_FIELDS_NOT_VALIDATED.

The 24 leads from corporate-action queue
14cfda6ed4d9c07c8fb19d105bb101d458b8770fcb98db1f394f78800b4c4f37
were located by PDF identity, hash-verified and processed with the new
page-bound extraction helper. The immutable output is
0462ecc5993643a9d5015edac742c8289c58d908fe9b4f969bcbc6b5dd41cf83.

| Measure | Count |
| --- | ---: |
| PDF leads | 24 |
| Candidate sentences | 639 |
| Sentences with an explicit recognized date field | 1 |

The queue is deliberately broad: it includes conversion, cash-option and
delisting announcements for sz000562 as well as equity-distribution leads. It
does not equate a candidate sentence with an accounting event.

Most Chinese corporate-action announcements place record date, ex date and
cash/share terms in tables or separate sentences. The extractor therefore
leaves absent fields absent. It does not infer dates from publication time,
derive cash/share terms from a title, or adjust Qlib prices. The next valid
step is an audited structured ledger for a specific event type with source
table/page anchors and exact candidate-date relevance.

Artifacts and the actual extraction script are retained under
artifacts/v2/exq_corporate_action_fields_20260919/. Candidate qualification,
formal PIT and formal research remain BLOCKED_DATA; CSI500 remains NOT_STARTED.
