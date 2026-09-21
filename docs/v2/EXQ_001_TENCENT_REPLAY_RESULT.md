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
| Summary | `3460b38e85ebe2162735c84407d3eead5b65a824172dcde6cd87bc1e4f3e3661` |

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

This result does not create a point-in-time exclusion, qualify an execution
price, alter a Qlib factor or label, or authorize BT-001. `FORMAL_PIT_STATUS`
and `FORMAL_RESEARCH_STATUS` remain `BLOCKED_DATA`; `CSI500` remains
`NOT_STARTED`.
