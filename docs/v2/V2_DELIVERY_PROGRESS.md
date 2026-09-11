# Quant V2 Delivery Progress

| Issue | Status | Evidence |
| --- | --- | --- |
| V2-000 Research charter | COMPLETE | Charter, dataset and experiment contracts frozen before capture |
| V2-001 Dataset registry | COMPLETE | Five pinned records, strict model, content-addressed capture and offline CLI |
| V2-002 Qlib/community import | NOT_STARTED | Must not start automatically |

V1 remains on its existing release-candidate branch and account paths. V2 writes
only below `docs/v2`, `configs/v2`, `src/quant_stack_v2`, `data/external` and
`artifacts/v2`, plus the minimal root CLI/package wiring needed to expose V2.

Current external metadata pins:

- `chenditc/investment_data` release `2026-09-10`, commit `b8c129b...`;
- `microsoft/qlib` release `v0.9.7`, commit `79633dd...`;
- `AI4Finance-Foundation/FinRL-Meta` release `v0.3.6`, commit `15405db...`;
- `QuantConnect/Lean` release `v2.4.0.1`, commit `8ee075a...`;
- `datasets/finance-vix` commit snapshot `07b0768...`.

No full external market archive has been downloaded or qualified.

Acceptance: 27 focused offline registry tests pass with 81% branch-aware module
coverage. Formal dataset validation
remains fail-closed until each non-fixture dataset has captured bytes, verified
coverage and an explicit `QUALIFIED` status through a later reviewed change.
