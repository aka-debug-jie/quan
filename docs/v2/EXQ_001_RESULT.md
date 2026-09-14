# EXQ-001：冻结候选范围数据资格化

状态：`BLOCKED_DATA`；结果 identity：`d76df75580daaebcba9ca918c9854aa255d37f5d0d88c3cfeef71f2ee39d7862`。

本审计只覆盖 AF-003 冻结的 CSI300 开发候选及其特征预热、信号和标签依赖。它不读取 CSI500，不导出原始行情或封存样本，也不构成全市场、正式 PIT 或正式研究资格结论。

## 范围与绑定

- 简单组合：`equal_weight_zscore`；机器学习 challenger：`NO_STABLE_ML_INCREMENT`。
- 候选：CN_REV_001, CN_REV_003, CN_PV_003, CN_RANGE_001, CN_VOL_003, CN_VOL_002, CN_PV_004。
- 必要 raw 字段：close, high, low, volume；标签：`close[T+2] / close[T+1] - 1`。
- 成员符号数：543；成员状态：`DERIVATIVE_CSI300_MEMBERSHIP_BOUND_NOT_FULL_PIT_QUALIFICATION`。
- 与候选所需范围相交的官方停牌区间：671；冻结 free residual 交集：278。

## 结论

执行所需的 raw OHLCV、官方公司行为、ST、T+1 成交价、涨跌停、整手、流动性和成本证据均未由已批准开发视图提供。开发视图的 adjusted Qlib 价格和有限成员修正不能替代这些证据，因此本候选范围为 `BLOCKED_DATA`。

`FORMAL_PIT_STATUS=BLOCKED_DATA`、`FORMAL_RESEARCH_STATUS=BLOCKED_DATA`、`CSI500=NOT_STARTED` 保持不变。

## 最小后续证据（未在本任务补取）

- 对上述冻结范围提供可复核的原始未复权 OHLCV、复权/公司行为、ST 与历史成员证据；
- 提供冻结的 T+1 成交、涨跌停、整手、流动性与成本规则；
- 若 free residual 交集非零，仅对机器结果列出的交集键补充最小证据。
