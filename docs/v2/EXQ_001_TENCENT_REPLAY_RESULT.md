# EXQ-001 Tencent raw-evidence incremental replay

Status: `BLOCKED_DATA`; raw execution is the only evidence domain released in
this replay.

The restricted root runner first validated every sealed Tencent manifest and
raw response against the frozen DEV-001 access scope, then compiled the
current evidence matrix and ran the replay twice with identical inputs. It
exports neither raw rows nor CSI500 data.

| Output | SHA-256 |
| --- | --- |
| Tencent aggregate verification receipt | `3eb31a1591e31029030810c2953d24363ff9c720a8c1b165b6fcbe9e4ba0da7c` |
| Qualification matrix | `83949570bc04d03d57a9045f3a7eacf340de05990d90e816ce6093537456c451` |
| Residual | `79ea900862500de5335fc9cafc096db5c4ae48f73d58bffd2d3fb8af36540dcc` |
| Summary | `d7925f612645074309c0733dd6ba4fe6c3c7047d9b7de88d65d982303d48d2f7` |

## Mechanical outcome

The validator receipt is accepted only when its scope, request coverage,
manifest identities and frozen DEV-001 provenance all match. The compiler can
therefore set `raw_execution=VALID`, while retaining its evidence level as
`INDEPENDENT_PROVIDER_CONFIRMED_NOT_OFFICIAL`.

The full candidate domain still has 543 frozen symbols and the matrix retains
278 exact candidate-residual keys. The seven remaining blocking domains are
`corporate_actions`, `trading_status`, `price_limit`, `board_lot`, `t_plus_one`,
`liquidity`, and `cost_model`. The three equity-distribution records remain
`FACTOR_RECONCILIATION_PENDING`; the sz000562 merger, cash-option and delisting
records remain event boundaries only.

The second replay's residual summary confirms that every one of those seven
domains blocks all 278 exact keys. They share the same 31 security scopes; the
content-addressed summary records each symbol's exact key count and first/last
signal-session bounds. The runner compared two independent replays before
publishing this result. This is the terminal `REPLAYED_WITH_RESIDUAL` outcome:
no further evidence collection or BT-001 action is scheduled from this branch.

This result does not create a point-in-time exclusion, qualify an execution
price, alter a Qlib factor or label, or authorize BT-001. `FORMAL_PIT_STATUS`
and `FORMAL_RESEARCH_STATUS` remain `BLOCKED_DATA`; `CSI500` remains
`NOT_STARTED`.
