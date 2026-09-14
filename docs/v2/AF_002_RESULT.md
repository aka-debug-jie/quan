# AF-002：开发期 Walk-forward 稳定性与因子去冗余

状态：`AF002_COMPLETED_LIMITED_DEV_DIAGNOSTICS`；结果 identity：`738aa277f047fe9e55af567c187a21ddefda5ded81100cfce62d05037b473c47`。
仅使用 DEV-001 CSI300 有限开发视图，不含组合收益、回测、模型调参、CSI500 或正式资格结论。

## 固定结论

- 低冗余候选数：7。
- 候选：CN_REV_001, CN_REV_003, CN_PV_003, CN_RANGE_001, CN_VOL_003, CN_VOL_002, CN_PV_004。
- 行业与市值暴露：`NOT_AVAILABLE_IN_APPROVED_VIEW`；未补取、推断或伪造这些诊断。
- 每个年度 fold 的样本、IC、Rank IC、ICIR、覆盖、缺失和方向，以及全部簇和淘汰理由均在机器可读结果中。

`FORMAL_PIT_STATUS=BLOCKED_DATA`、`FORMAL_RESEARCH_STATUS=BLOCKED_DATA`、`CSI500=NOT_STARTED` 保持不变。
