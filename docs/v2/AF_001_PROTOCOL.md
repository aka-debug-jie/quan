# AF-001：CSI300 Alpha158 可解释单因子筛选

状态：`PREREGISTERED_PENDING_RESTRICTED_REPLAY`。本协议在读取 DEV-001 development
view 前冻结；不构成 Alpha 发现、组合收益、正式资格或 promotion 结论。

## 范围与输入

- 仅限已完成的 DEV-001 CSI300 `LIMITED_DEV_RESEARCH` view。
- registry：`configs/v2/alphas/af_001_alpha_registry_v1.yaml`，固定 16 个直接
  Alpha158 列变换；不读 raw OHLCV、不导出新 view、不读 CSI500、不联网。
- 特征身份：`2e3607d5e4fca26ee901c8d97ec692d5427b2332fe509eda8288e218ddcda92d`。
- 使用合同 SHA-256：`a799cbfe2cb7eb9e5700405abbca9505fc2be26b22adab7ac7d62fabee76e74e`。
- 标签：`close[T+2] / close[T+1] - 1`，即固定交易日 T+1 至 T+2 的单日收益；
  本任务不得变更 horizon 或用自然日替代交易日。

运行器严格重开 DEV-001 summary、contract、evidence、view pin、view manifest 和
validation-target manifest，并重算每个发布分片的身份。registry 中每个
`source_feature` 都必须与 resolved Alpha158 的同名精确表达式一致。

## 评价规则

每个 `session + symbol` 一对一连接。样本身份来自 member-at-T 与已发布完整特征
view，不因 T+1/T+2 标签缺失或未来成员状态改变 T 的预测资格。

- 每日 Pearson IC 和 average-tie Spearman Rank IC；至少两个有限、非常数的截面行。
- 总 IC / Rank IC 为有效交易日等权均值。
- ICIR / Rank ICIR 为相应日度序列的 `mean / sample_std(ddof=1)`，不年化；不足
  两日或零方差为 `null`。
- 方向一致率为日 Rank IC 严格大于零的比例；零不计为一致。
- 固定分段为 resolved contract 的四个 2020 自然季度和 validation 全年。
- `CANDIDATE_PENDING_AF002` 需要预注册的：至少 30 个有效日、成员网格评价覆盖率
  至少 0.5、平均 Rank IC 为正、方向一致率至少 0.5。否则为
  `REJECTED_NO_STABLE_SIGNAL`；无可定义截面则保留 `REGISTERED`。

这些 disposition 只服务 AF-002 的后续复核，绝不使用 `RESEARCH_CANDIDATE` 等
正式 promotion 状态。

## 缺失与已知限制

DEV-001 的发布 view 在下游前已剔除任一 Alpha158 特征不完整的行。因此报告必须
区分 member-grid coverage、发布 view 内因子缺失、标签缺失和 exporter 的 aggregate
feature-cell 缺失率；不得把 aggregate 缺失率说成某个因子的 member-grid 缺失率。

2020 validation 标签已在 DEV-001 开放。本次结果会标为
`LABEL_PREVIOUSLY_EXPOSED_IN_DEV001_NOT_FRESH_HOLDOUT`。正式 PIT / research 保持
`BLOCKED_DATA`，CSI500 保持 `NOT_STARTED`。未生成 CAGR、Sharpe、持仓、成交、成本
或收益结论。

## 两阶段执行

先提交 registry、协议、运行器与合成测试；之后由受限环境在干净 commit 上执行
`scripts/v2/run_af001.sh` 一次。运行结果绑定 registry SHA、代码 commit、DEV-001
summary、contract、evidence、view、validation target 与 calendar SHA。结果发布后不得
回改公式、阈值、日期或 registry；若发生工程修复，必须保留失败记录并重新预注册。
