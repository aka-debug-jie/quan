# 官方调样日期核验与深市63日残余

2026-09-13，本轮五只证券的CSI300官方调出日期已核实。用户已完成受限回放并导出六只证券的成员元数据：摘要与本地结果核对一致，缺失日残余从114日降至63日、23个区间。

## 五只证券的中证官方调出日期

| 证券 | 调出生效日期 | CSI原始公告 | 名单定位 |
| --- | --- | --- | --- |
| 600005 武钢股份 | 2017-02-14 | id=4794，2017-02-09 | 官方XLSX“调出”页A30:D30 |
| 600832 东方明珠 | 2015-05-20 | id=6802，2015-05-14 | 官方正文000300行，调入000738 |
| 601299 中国北车 | 2015-05-20 | id=6802，2015-05-14 | 官方正文000300行，调入300003 |
| 600837 海通证券 | 2025-03-04 | id=15546，2025-02-06 | 官方XLSX A28:F28 |
| 601989 中国重工 | 2025-09-05 | id=1006022，2025-07-25 | 官方XLSX A43:F43 |

日期不是直接拿退市日替代指数日期：四份中证公告明确将相应沪深300样本调整绑定到该证券退市生效日；再由已归档的上交所原始终止/摘牌公告提供日历日期。主代理与独立强模型复核均确认名单方向、指数代码、证券代码与条件日期关系。

官方API可直接读取：

- [武钢股份调样原文](https://www.csindex.com.cn/csindex-home/announcement/queryAnnouncementById?id=4794&lang=cn)
- [东方明珠、中国北车调样原文](https://www.csindex.com.cn/csindex-home/announcement/queryAnnouncementById?id=6802&lang=cn)
- [海通证券调样原文](https://www.csindex.com.cn/csindex-home/announcement/queryAnnouncementById?id=15546&lang=cn)
- [中国重工调样原文](https://www.csindex.com.cn/csindex-home/announcement/queryAnnouncementById?id=1006022&lang=cn)

2015年公告当前附件已被替换为资讯商提示，未用于结论；官方正文仍保留两条完整沪深300调出行。二手材料的5月21日线索不替代官方原文“退市之日起”与上交所5月20日生效日。

核验报告：`artifacts/v2/csi_verified_adjustments/732e50f7caf89501150341ef378f04b8ce2738e9f7ed99d5f3d3140e813d9389.report.json`。该目录保存四份CSI响应、三份附件、五份SSE原件及可复验构建脚本；另七次官方下载回执与归档源SHA逐一一致，保存于`artifacts/v2/szse_last114_evidence/csi-receipts/`。

这只证明五个调出日期。完整成员区间起点、其他调样事件及全体成分对账尚未完成，因此不生成PIT成员资格PASS。新发现宏源证券000562在2015-01-26终止上市以后仍有四个成员缺失日，该新增异常也需独立处理。

## 深市缺失日

本地112条历史证据清单及独立退市证据得到：

| 分类 | 日数 |
| --- | ---: |
| 原深交所月报 | 2066 |
| 已发生复牌类证据 | 2576 |
| 有界历史 | 3384 |
| 退市后日期（独立分类） | 4 |
| 合计解释 | 8030 |
| 尚未解释 | 63 |
| 冲突 | 0 |

新增BOUNDED_START_TO_PLANNED_BOUNDARY只接纳同一最终公告、同页公司股票的起始停牌与明确复牌边界；包含签署日/披露日约束和窗内已复牌反证，不将计划复牌变为实际复牌。宏源的连续停牌表述解释2015-01-05至01-21的13日；其退市公告转述深交所决定，单列2015-01-26至01-29四日为POST_DELISTING，来源级别保留为ISSUER_NOTICE_REPORTING_EXCHANGE_DECISION。01-22和01-23未因退市计划自动获解释。

- 历史清单：`artifacts/v2/szse_history_evidence/267da4f7d6f162b87058a784c07dfcefeae7a5eda6b30c5add28f7261b9756d3.json`
- 退市清单：`artifacts/v2/szse_lifecycle_evidence/3ac2dbd5ce391810ec51a5e10b4d4646afaad48f0ca5a3cefc06da0e9fc9ff09.json`
- 全量本地匹配：`artifacts/v2/szse_local_matching/bc546bea67149f0dc28ad74a69cf25bbcf03cbcafb17da559bc7ad55245c623f.json`
- 63日逐日残余：`artifacts/v2/szse_local_matching/066e89796a17add5a5bb7fc208f408e660413d9370847454ee30b6d31d79b120.residual.json`

残余不等于“无免费证据”：仍包括未接入的配股发行公告、跨页事件端点、签署截止日后的日期、缺少同事件起点的最终公告、原文年份冲突，以及开市停牌安排与实际执行证据的区别。原有证据和拒绝的候选清单全部保留，不扩大本轮已接受集合来强行清零。

## 验收和待执行步骤

Ruff全仓库通过，格式173文件通过，mypy78源文件通过；完整离线pytest335项通过，84.47秒，coverage73.18%。六个追加公告未改代码，使用相同验收后的引擎全量加载和匹配通过。专门回归验证生效日包含当日、冲突保留、已解释停牌与退市不重复计数，以及新有界证据的窗口内复牌拒绝。固定元数据导出脚本已用合成数据确认只输出六个指定证券的日期且拒绝额外列。

验收包：`artifacts/v2/szse_next_qa/58820b67a0f1621dcc8a317ccf9862a061c69fac3dece7e1c84a5b89028cff53/`。

一次执行入口：`scripts/v2/verify_szse_and_membership.sh`。它检查当前源码/清单哈希，运行最新sealed回放，再只导出五只已核实证券及宏源证券的Qlib成员起止日期、元数据文件SHA；不导出价格，不改原文件和权限。原始文件位于sealed，当前普通账户不能读取，所以这一步仍需用户执行。脚本输出回放摘要和成员摘要两个0600临时文件路径。拿到成员区间后才能逐条核对并提出明确的区间修正，不从调出日期倒推出全部历史成员资格。

旧`verify_szse_complete.sh`和`verify_szse_consolidated.sh`保留历史哈希，已不适用于当前代码。两个gate仍独立BLOCKED_DATA；本轮8030日/63日已获用户受限回放摘要确认，无需重跑本次命令。

## 回放确认与成员终点派生修正

回放确认记录：`artifacts/v2/szse_replay_confirmation/8d67de5e4c6e782baa10dac4577da30040d37543e607a87aa453325afffb8995.confirmation.json`。确认总数、分类增量、逐证券增量、代码及证据身份、23个残余区间均一致；FULL=319、PARTIAL=20、NO_MATCH=3、CONFLICT=0。摘要记载完整受限报告为`/srv/quant-v2/sealed_holdout/artifacts/v2/free_suspension/szse_history_verification/420c6a5d04ef02b3406742e66daa41e2b054dc9442af78c80f3d6737b406f743.json`，未直接读取或独立计算其完整文件哈希。

六只证券共174条成员区间已释放。五只沪市证券各有一个区间延长到官方调出日之后。按Qlib日期终点包含当天的语义，仅将派生副本的终点截到调出日前一天：

| 证券 | 原终点 | 派生副本终点 |
| --- | --- | --- |
| 600005 | 2017-06-29 | 2017-02-13 |
| 600832 | 2015-05-28 | 2015-05-19 |
| 600837 | 2025-06-29 | 2025-03-03 |
| 601299 | 2015-05-28 | 2015-05-19 |
| 601989 | 2025-12-30 | 2025-09-04 |

所有起点和其余区间保留，检查派生副本内这五只证券不再有跨越已核实调出日的区间。完整原成员文件未修改；五个终点的局部修正不构成完整PIT资格。宏源证券原区间2014-12-31至2015-01-29仍保留，CSI正式调出日尚未取得，不能只按退市日改成已核实的CSI区间。

修正副本、原行/新行对照和输入身份：`artifacts/v2/csi_member_reconciliation/1351f115fea9ab3caa9901fac32cb8877fae855aef6fa8b08ff1dc19de13f000.reconciliation.json`。已逐条检查174行的字段、日期、唯一性与符号范围，并验证恰有5行修改。原始完整成员文件SHA为用户脚本报告的`003802602c126aa24153e103836ffbf13ee993a191adf81a19f84247a2da074c`，当前账户未独立读取该原文件。剩余63个缺失日和完整成员历史资格继续保持BLOCKED_DATA。
