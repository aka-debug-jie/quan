# EXQ-001 pagination and local PDF recovery

This is a follow-up engineering/evidence review, not a qualification upgrade.
The original discovery and qualification artifacts are unchanged.

## Actual evidence collected

- Re-fetched only the eight fixed CNINFO PDF URLs already listed in discovery receipt c619ec2af0086d5c9bb83a4d595e5668e981dbfcb4f3509882c3eaad095dacd4. Every downloaded body matched its original PDF SHA-256.
- Together with 54 previously verified local copies, all 62 PDF bodies are now available for local review. Full-sentence extraction produced 245 page-numbered candidate anchors.
- The temporary content-addressed local inventory is /tmp/exq-local-review/b61b9bb8104616ccb4f328da2fdf7a89857eaa5995b2b44e7f28dd7448a7bd96.json. This is a local review artifact; the authoritative sealed receipts remain separate.
- A live pagination check for sz000793 used the existing discovery window 2015-05-02 through 2016-01-02. It returned 110 unique announcements across four pages. The merged catalog SHA-256 is d36c0ba084c8d906f8183ee4d3448f19725f15f4677124604a1c9f835072d655, archived under /tmp/exq-pagination-live/cninfo_catalogs/. The earlier first-page-only adapter could not inspect this complete catalog.

## Engineering changes

The catalog adapter now archives the security mapping, each response and the
exact form parameters. It follows hasMore, checks totalAnnouncement and unique
announcement identities, and rejects changing totals, repeated pages or the
100-page limit. Retrieval receipts have separate content identities, allowing
repeat captures without overwriting history. A batch with failed issuer tasks
now reports DISCOVERY_PARTIAL.

## Interpretation and remaining work

The Hongyuan notice 12af09a8522ba0c2a206de36d65105514b9302b752c7b96c5d3be3600870d84c describes suspension from 2014-12-10, no further trading, cash-option procedures and conversion through absorption merger. Its contents require lifecycle/company-action adjudication; a zero-event suspension query alone cannot resolve them. This review does not infer actual conversion completion or payable cash from a plan.

The full 28-issuer catalog replay, reviewed claims, exact session matching and
corporate-action accounting validation remain incomplete. Zero candidate hits
from the prior first-page-only run are not exhaustive negative evidence.
No additional residual is classified as explained in this update.

EXQ status remains BLOCKED_DATA. FORMAL_PIT_STATUS and FORMAL_RESEARCH_STATUS
remain BLOCKED_DATA; CSI500 remains NOT_STARTED.
