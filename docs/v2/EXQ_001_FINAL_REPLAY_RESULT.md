# EXQ-001 final candidate qualification replay result

Status: `BLOCKED_DATA`.

The fixed read-only restricted runner completed two independent replays against
the same frozen inputs. Its byte-identical JSON outputs prove deterministic
reconstruction; no market values, CSI500 rows or sealed samples were exported.

| Output | SHA-256 |
| --- | --- |
| Qualification matrix | `f0a304658b93c8b41a564b23459041d0c725993c69f65fdf5522fc6ec52efda6` |
| Residual | `db2102ae151c3f4eac411f4e59f3069f66857fa6664dd919e5b3836ace75c7d6` |
| Summary | `98849de2a02dc52d39095b4874242202743420bd9e6891e6cbbd86778fb80794` |

## Matrix outcome

The matrix contains 278 exact candidate-residual keys. Every key is
`BLOCKED`; the full candidate domain is represented by 543 frozen CSI300 member
symbols and remains blocked by raw execution, corporate actions, trading status,
price-limit, board-lot, T+1, liquidity and cost-model evidence.

The three in-range equity distributions remain
`FACTOR_RECONCILIATION_PENDING`. The `sz000562` merger, cash-option and delisting
entries remain event boundaries and have not been converted into execution-price,
cash-settlement or CSI-membership claims. Retrospective issuer history and empty
provider rows were not used as T-known exclusions.

`FORMAL_PIT_STATUS=BLOCKED_DATA`,
`FORMAL_RESEARCH_STATUS=BLOCKED_DATA`, and `CSI500=NOT_STARTED` remain unchanged.
This result closes the implemented EXQ replay as a negative qualification result;
it does not authorize BT-001 or portfolio research.
