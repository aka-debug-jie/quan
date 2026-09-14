# AF-003：简单组合与机器学习增量诊断

状态：`PREREGISTERED_PENDING_RESTRICTED_REPLAY`。仅在已触达的 DEV-001 CSI300
`LIMITED_DEV_RESEARCH` view 内，使用 AF-002 结果 identity
`738aa277f047fe9e55af567c187a21ddefda5ded81100cfce62d05037b473c47` 的七个候选。
这不是未见样本、组合回测、收益结论或正式资格升级。

`af_003_combination_v1.yaml` 在产生任何 AF-003 模型拟合或诊断结果前固定四个扩展训练窗口：
2015--2016 训练/2017 诊断，随后依次扩展训练期并诊断 2018、2019、2020。每个模型只
在对应训练窗拟合标准化与训练 Rank-IC 权重，绝不使用测试 fold 标签拟合或选择参数。

顺序固定为 equal-weight daily z-score、training Rank-IC weighted daily z-score、Ridge、
ElasticNet、LightGBM 和 XGBoost。树模型固定三个种子 0/1/2；线性模型为确定性求解，
seed stability 标为 `NOT_APPLICABLE_DETERMINISTIC`。每 fold 保存 Rank IC、相对 equal
weight 的增量、最差 fold、种子范围、模型或权重的重要性漂移，以及将一个候选分数以
训练均值替换时的测试期 Rank-IC 敏感性。

简单组合按四 fold 平均 Rank IC、model id 选一项。复杂模型必须平均 Rank-IC 增量为正，
且至少 75% folds 对 equal weight 增量为正，才可按平均增量、model id 选至多一个
`ML_CHALLENGER_PENDING_AF004`；否则明确 `NO_STABLE_ML_INCREMENT`。这些都是开发期
诊断，不能称为 Alpha、策略、收益或正式 research candidate。

不读取 CSI500、sealed test 或 raw OHLCV；不联网、参数搜索、组合回测、CAGR、Sharpe、
交易或任何 promotion。候选已使用 AF-002 的 2017--2020 标签选择，因此即使模型按时间
折叠，本轮仍是完全触达的开发期复用，不能表述为未见验证。`FORMAL_PIT_STATUS=BLOCKED_DATA`、
`FORMAL_RESEARCH_STATUS=BLOCKED_DATA` 与 `CSI500=NOT_STARTED` 保持不变。
