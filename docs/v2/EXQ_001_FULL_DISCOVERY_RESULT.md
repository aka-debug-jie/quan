# EXQ-001 full paginated discovery result

Status: DISCOVERY_COMPLETE; CLAIM_REVIEW_PENDING. Candidate qualification
remains BLOCKED_DATA. This run used the 28 issuer tasks returned by the user
from monthly replay e60a76448db4b23ae8872b716dd0f422cd2ddf878f99c078c6f1dc5814bf0919.
It retained their original discovery windows (first residual minus 30 calendar
days through last residual plus 30 days), without modifying the 275 exact
SZSE residual keys.

## Actual run

| Measure | Count |
| --- | ---: |
| Issuer windows completed | 28 |
| Catalog pages archived | 64 |
| Announcement records | 1,451 |
| Relevant candidate PDFs reviewed for extraction | 155 |
| PDF capture/extraction failures | 0 |
| Full page-numbered candidate sentences | 630 |
| Issuers with candidate PDFs | 27 |
| Withdrawal/cancellation candidates retained for review | 1 |

sz002673 has no title-selected candidate in this completed window. This is not
proof of no relevant announcement outside the window or under other wording.
Candidate selection included suspension, resumption, ex-right/ex-dividend,
equity distributions, risk warnings, conversion and delisting titles. It did
not discard cancellation titles; these must be considered during adjudication.

## Provenance and storage

The immutable catalog replay hash is
087dd57d137a0d79cefad0634819d7f43c6c2cd1aedc14acb53ddc374c775eea.
The PDF inventory and extracted-anchor hash is
33ce8849b1542fc7c304a04fd18b97a2c38678800171cb130c031a29a58d305a.

Both artifacts, actual batch scripts, page responses, request receipts, stock
maps and new PDFs are retained under
artifacts/v2/exq_cninfo_paginated_20260919/. Existing verified PDF copies are
reused via the inventory's source paths. Eight recovered copies are retained
under recovered_fixed_pdfs/. Paths beginning /tmp/exq-all-catalogs/ in the
run inventory map to the persistent archive root above; /tmp/exq-local-review/
recovered/ maps to recovered_fixed_pdfs/. These are publicly downloaded issuer
documents, not an export of sealed market samples. The original sealed
discovery receipt is unchanged.

## Remaining qualification work

No additional session is classified as explained by this discovery run.
The 630 sentences still require issuer identity, actual versus planned dates,
continuity, cancellation and exact dependency matching. Corporate-action
cash/share accounting and historical trading-rule qualification are separate
and incomplete. Download/extraction success is not a qualification PASS.

FORMAL_PIT_STATUS=BLOCKED_DATA; FORMAL_RESEARCH_STATUS=BLOCKED_DATA;
CSI500=NOT_STARTED. No model training, portfolio backtest or external test ran.
