# 深市集中补证及离线验收

2026-09-13。当前本地完整匹配解释 **7979 / 8093 日**，残余 **114 日、32 个区间**，冲突0。相比上一份受限回放的7813日，本地新增166日；相比本轮开始的7891日，本轮新增88日。用户已执行受限回放，释放摘要与本地计数、逐证券增量、证据及引擎哈希、32个残余区间范围核对一致；不构成最终数据资格通过。gap和PIT成员gate均保持BLOCKED_DATA。

## 本轮补证与修复

原临时查询把机构编号拼接为`gssz0+证券代码`，对部分002/300证券返回空目录。本轮使用已归档的巨潮官方证券机构映射查询，并补齐有后续页的目录。分页按服务端实际30条大小请求；50条参数下后续请求曾重复首页，未将重复响应认定为完整检索。公告标题未含停牌/复牌的其他文件未在本轮全文穷举；未抓到资料不能解读为资料不存在。

历史证据从91条增至102条，新增中国宝安、攀钢钒钛、海康威视、光线传媒、亚厦股份、金螳螂、乐普医疗、碧水源、国新健康、桑德环境、海格通信11条。所有新增公告已核对同事件上下文、证券代码、签署日期和公开目录；提取锚点再由程序复验。持续状态只覆盖起点之后、`min(披露日期, 签署日期+1日)`之前的日期，不延长到未来计划复牌日。

收紧了无计划复牌日记录的持续状态要求；拒绝匹配到本公司股票在覆盖窗口内已经复牌的明确日期表述。跨页片段须与主记录页码一致且非空；CLI回归测试覆盖两个gate的四种组合。正则不是通用语义证明，仍依赖逐份上下文审阅。

## 证据与结果

- 新历史清单：`artifacts/v2/szse_history_evidence/2cd45380d1da5b7d43cdfc6116bb12df36e827c02fc3f199e132e76875852ca8.json`
- 完整本地结果：`artifacts/v2/szse_local_matching/c05fb361b73d45284163c58af795a6c516592bf8dbadf45b5d5af671f8b26230.json`
- 全部残余日期：`artifacts/v2/szse_local_matching/b75217a7e487fe7d285884acc4e4e12830744591e395c9ebbd86af8227f0fdf4.residual.json`
- 公开抓取原件、目录、索引及构建脚本：`artifacts/v2/szse_consolidated_evidence/`。原件和旧清单均保留；归档的候选不等于已接受证据。
- 验收：`artifacts/v2/szse_consolidated_qa/7f437e6d30b34ce974525adae122575df91308af55b6b6e95047edec621a6b48/acceptance.json`

原月报解释2066日，实际复牌类公告解释2576日，有界历史解释3337日。残余包括截止日以后的日期、缺少明确持续性或起点的材料、原文日期矛盾、未获得可接纳公告的区间。残余并不表示已证明正常交易，也不表示免费来源已经穷尽。

## PIT独立结果

600005、600832、600837、601299、601989的沪深300官方调出日期仍未核实。本轮找到并核对了相关上证指数公告，但它们不能替代沪深300调样原始名单：

- [武钢股份退市的指数调整公告，2017-02-09](https://www.sse.com.cn/market/sseindex/diclosure/c/c_20170209_4235948.shtml)
- [上证180、上证50、上证380等调整公告，2015-05-14](https://www.sse.com.cn/market/sseindex/diclosure/c/c_20150911_3985142.shtml)
- [上证180样本调整公告，2025-02-06](https://www.sse.com.cn/market/sseindex/diclosure/c/c_20250206_10770824.shtml)

不把退市日期、其他指数调整日期或常规定期调整规则填成CSI300生效日期。官方检索原件另存`artifacts/v2/csi_pit_search/`。

## 最终离线验收及单次回放

Ruff全仓库通过，格式169文件通过，mypy77源文件通过；完整离线pytest **327 passed**，84.09秒，coverage **73.09%**。项目未设置覆盖率最低阈值。没有购买数据、使用Tushare、训练模型或放宽sealed权限。

最新固定入口为`scripts/v2/verify_szse_consolidated.sh`；旧`verify_szse_complete.sh`为历史版本，其旧源码哈希不能用于当前代码。新入口已固定当前源码和102条清单哈希；普通用户运行脚本，内部仅最终回放调用sudo。回放结果写入sealed新内容寻址报告，只释放计数和残余搜索范围到用户拥有的0600临时JSON。任一gate阻断退出1。这一次回放已完成，摘要核对一致；不需要重跑。不能将工程验收通过表述成停牌或成员资格PASS。

## 受限回放确认

回传摘要SHA-256：`19848f78ac4b7eb3419b2d0a5147b04946f77650de0bc7ad1deb5d12a606fd88`，归档于`artifacts/v2/szse_replay_confirmation/`。完整受限报告路径由摘要记载为`/srv/quant-v2/sealed_holdout/artifacts/v2/free_suspension/szse_history_verification/2de6a2eac80840e0ef0cb0147deed81a8e4f00edcaae4f6fc90da8094f2a8ebe.json`。当前用户未读取该完整报告，因此未独立校验其文件哈希或逐日正文。

已解释7979日、残余114日；FULL=310、PARTIAL=28、NO_MATCH=4、CONFLICT=0。两个gate仍为BLOCKED_DATA。
