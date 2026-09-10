# Issue 009-D0 Frozen Universe Data Qualification

Status: `BLOCKED_DATA`
Substage: `009-D0`
Locked test: not run

This report is a pre-locked-test qualification artifact. It does not report a
strategy result and does not alter the frozen universe, benchmark, strategy,
cost model, timing rule, parameter grid, or split.

## Current full-universe scan

Artifact: `artifacts/data_qualification/931fee31624d99f297d8a43e16c72c2534ce04998a793102120e180685fdb297/qualification.json`

| Symbol | Raw / sessions | Ledger | PIT causal | Adjusted | Execution raw | Result |
| --- | --- | --- | --- | --- | --- | --- |
| `510300` | PASS | incomplete; 10 verified + 2 retrospective candidates | FAIL | missing | PASS | NOT_QUALIFIED |
| `510500` | PASS | incomplete; 6 verified events | FAIL | missing | PASS | NOT_QUALIFIED |
| `159919` | PASS | complete + archived | PASS | available | PASS | QUALIFIED |

`510300` 的独立 Sina/AKShare raw reconciliation 已保存为
`f495551c61d1038754dec93fd961ede728f4ba87507c0dfb245c450b0c0f115c`：
2,841 个重叠会话中 8 个 OHLC 不一致，最大绝对差 `0.002`、最大相对差
`0.0005395198273536552468303210143`，且无公司行为边界差异。Sina shares-to-AKShare lots 的
`2` 手容差只处理可复核的 JavaScript 浮点成交量精度，未放宽 OHLC 比较；
所以该资产仍不能通过 D0 cross-provider gate。

`510500` 的独立 Sina/AKShare raw reconciliation 已保存为
`284817f8cca5c90062cd72f35dd34cb20279c2120f0e32814eef44400e1f3bdc`：
2,839 个重叠会话中 6 个 OHLC 不一致，最大绝对差 `0.002`、最大相对差
`0.0002631578947368421052631578947`，且无公司行为边界差异。相同的 volume precision 规则不能
覆盖价格差异，故该资产也保持 D0 cross-provider blocked。

Tushare 未安装且当前环境没有配置 `TUSHARE_TOKEN`；因此它不能作为第三个
cross-check provider。该缺失未被用作放宽 Sina/AKShare 的 0.002 价格差异，
也不要求在仓库或日志中提供任何凭据。

2026-07-15 的 `510500` 分红已完成 authoritative evidence chain：上交所
availability 证据 `944367139323420ab7e6efd2ec690181f82b2e2abdad31335f776d314ddf8455`
确认公告日与除息日；南方基金 2026 年中期报告 value 证据
`01136d5f27e09722b45876afe96bc30070635b76495c95d656b0c34b44a07861`
在 §6.4.8.2 记录截至 7 月 14 日登记、每 10 份 1.4900 元。value evidence
发布于 2026-08-31，ledger 记录为 retrospective verification，未回填到事件当日。
该单事件通过不改变 `510500` ledger incomplete 或其 `NOT_QUALIFIED` 状态。

`159919` passed the D0 cross-provider and reproduction gates: report
`ab424736c7ffbd1e1dfe517e7cc2f02f85609c56da5d6ac30bfe067b8ca2d739`
records 201 overlapping sessions with zero mismatch; reproduction artifact
`8ac4974e31a59b401444fc3dc00e6fff05f8837492dff982c7246e9623ad5938`
recreates the same causal manifest and output SHA-256. This does not alter its
accepted Issue 003 history.

## Candidate inventory

The retained provider raw/qfq pairs are discovery-only. Their exact qfq/raw
ratios change on 2,653 sessions for `510300` and 2,785 sessions for `510500`.
Because each relation changes on more than half of observed sessions, the D0
diagnostic classifies the whole provider-factor relation as
`PROVIDER_ARTIFACT`, not as a discrete corporate-action ledger. This does not
make either provider qfq series canonical. Discrete raw-price discontinuities
and official-announcement inventories remain independently reconcilable.

## Promotion rule

All three frozen assets must be `QUALIFIED` before a new locked-test precommit
manifest can be generated. No locked test, walk-forward result, robustness
result, or Issue 010 work is permitted while this report is blocked.
