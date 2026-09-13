# 深市缺失日审计：统一本地匹配与最终复算

2026-09-13，用户已执行固定受限复算脚本，回传摘要与本地结果核对一致。免费公告证据解释了 7813 / 8093 日，仍有 280 日未获当前规则接受。结果是回顾性缺口解释，不构成 PIT 成员资格证明；gap gate 和 membership gate 均为 BLOCKED_DATA。退出码1是gate阻断的预期结果，不是脚本运行失败。

本次核对覆盖总数、逐证券增量、证据清单和引擎哈希、全部区间统计，以及33个残余区间的起止范围和日期数。当前账户只读取用户脚本释放的摘要，未直接读取sealed完整报告，因此不宣称已独立重算完整报告文件的SHA-256或重新检查其全部逐日证据正文。

回传摘要已不可变归档：`artifacts/v2/szse_replay_confirmation/b26036df0aa968c2e5da7e0a58d563192653e297e095d4cfe6d8b98b67805cab.json`。摘要记载的完整受限报告为 `/srv/quant-v2/sealed_holdout/artifacts/v2/free_suspension/szse_history_verification/758c6cfed64d640ccdd1ba1c4b34269052b8a0ce952ac33e12d36a6148ad3164.json`。

| 证据类型 | 解释日期数 |
| --- | ---: |
| 原深交所月报 | 2066 |
| 已发生复牌公告/回顾性报告，20条累计证据 | 2576 |
| 有明确截止日的连续停牌历史，89条累计证据 | 3171 |
| 合计 | 7813 |
| 未解释 | 280 |
| 匹配冲突 | 0 |

相对用户回传第五批的4522个已解释日期，本轮增加3291日。所有8093行已释放日期都参加匹配，无价格字段。用户导出文件已按SHA-256归档，匹配入口锁定其完整哈希，禁止以截断输入产生有效统计。

受限复算区间统计：FULL=309、PARTIAL=29、NO_MATCH=4、CONFLICT=0，共342个区间；残余33个区间、280日。本地重建使用第四批完整127任务队列及该批已确认的215个FULL区间，并验证每个当前残余日期恰好归属一个任务；该重建统计已与受限复算摘要逐项核对一致。

## 文件

- 完整逐日匹配：`artifacts/v2/szse_local_matching/d4ab5fd0d6255f74ae96f78a043e462eb3dcfba82db798930e5b5b5fd849ad22.json`
- 全部残余日期及原因：`artifacts/v2/szse_local_matching/786957593ad61b9b0768ea5b6185a36c3de7dff59119cd4547cbc3e835d07192.residual.json`
- 89条历史证据清单：`artifacts/v2/szse_history_evidence/ef863669718b237fdb5c74e2df4b8f7de1cf5b174e9ae0b4f33dc3d690fcaf35.json`
- 已释放日期：`artifacts/v2/szse_released_dates/169b28c92d4fc00325e6f4b06aa560c9a16e9ad2b674102a5ec61b5ec0cae211.json`
- 验收及复核记录：`artifacts/v2/szse_completion_qa/555abc3ca8344efc6767a69e7780d8c47ebb059bf85994b7c695113e2a52940a/`

原证据及历史清单保留；只有上述最终清单用于此次复算。归档中的早期候选清单不等于已接受证据。

## 证据边界

有界历史记录要求同一官方公告给出原始停牌起点和同事件的连续停牌叙述。上下文经逐份复核，机器再核验目录记录、PDF字节、证券代码、发行人文字和逐页锚点。部分锚点保留整页上下文；字符串出现本身不能单独证明语义或同事件关系。

只匹配 `start_date < session < min(publication_date, signed_date + 1日, planned_resume_date)`。不采用计划复牌日，不将计划表述转成实际复牌，固定 `actual_resume_date=null`、`closed_actual=false`、`right_censored=true`。跨页日期必须由相邻页正文尾、正文首的原文片段拼接，页码不参与日期。官方目录时间戳按北京时间核对。

140个月表中区间内的另一停牌起点、实际复牌，以及已核实发行人实际复牌均用于反证检查。历史证据仅解释UNEXPLAINED，不覆盖原有冲突或其他已解释状态。原月报对9999开放记录的按月约束保持不变。

残余不是“已证明正常交易”。包含未取得相应公告、原文未明示起点或持续性、原文年份冲突、签署状态截止日后的日期，以及当前核验器尚未接纳的关联日期句式。例如攀钢2015年报告的“于当日恢复交易”仍未作为闭合公告输入，不能将这一实现边界误报成完全没有免费数据。欧菲光2019年更新公告中的起始年份矛盾保留为拒绝证据，未擅自更正。完整原因在残余JSON。

## 验收

- Ruff全仓库PASS；格式检查168个文件PASS；mypy 77个源文件PASS。
- 完整离线pytest：322 passed，82.52秒；覆盖率73.03%（项目未配置覆盖率最低阈值）。
- 新增回归覆盖本地与原引擎计数一致、哈希与重复日期、截止日、北京时间日期、签署字形、实际复牌反证、跨页误拼拒绝、区间计数及PIT退出码隔离。
- 未购买数据、未使用Tushare、未训练模型、未调整sealed权限、未启动桥接服务。

## 一次性受限环境复算

以普通账户执行：

```bash
bash scripts/v2/verify_szse_complete.sh
```

脚本先检查固定代码和两份证据清单哈希，然后通过sudo调用已有受限运行环境。它只读原固定月报报告，在sealed内新增内容寻址报告；只把计数和残余搜索范围写入普通账户创建的0600临时文件 `/tmp/quant-szse-final.*.json`。执行结束显示该路径，无需复制长JSON。任一gate仍BLOCKED_DATA时退出码1为预期；gap PASS也不能以退出码0掩盖membership BLOCKED。

完整报告保留在 `/srv/quant-v2/sealed_holdout/artifacts/v2/free_suspension/szse_history_verification/`。本次受限复算摘要已与本地结果核对一致，当前无需重跑该命令。280日缺口和PIT成员资格问题仍未解决，不能把复算完成或工程验收通过写成数据资格PASS。
