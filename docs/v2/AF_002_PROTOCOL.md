# AF-002：开发期 Walk-forward 稳定性与因子去冗余

状态：`PREREGISTERED_PENDING_RESTRICTED_REPLAY`。本协议仅使用已完成的 DEV-001
CSI300 `LIMITED_DEV_RESEARCH` view 与冻结 AF-001 registry/result，不构成 Alpha
发现、收益、组合、模型选择、正式资格或晋级结论。

## 固定输入与边界

- AF-001 registry identity：`cef1062c32388bc97efa086c4ff917b7a32e4b33897c0c47ffcad2f228af38bb`。
- AF-001 result identity：`d89d25f06e0b5c1885d81b434fccb5c973a25922d5b525d46c04edbd58116e62`。
- DEV-001 summary identity：`606b072c361fd73f0da29d4ae4070dac31cf2e2a11f184be09fe929b06b13472`。
- 标签固定为 `close[T+2] / close[T+1] - 1`。2020 标签已经在 DEV-001 中开放，
  不是新鲜 holdout。
- 不读取 CSI500、sealed test 或 raw OHLCV；不联网、参数搜索、模型训练、组合回测、
  收益报告或资格升级。

## 固定评价与选择规则

`configs/v2/alphas/af_002_walk_forward_v1.yaml` 在读取 AF-002 输入前已冻结四个
自然年 folds：2017、2018、2019 和 2020。只复核 AF-001 的
`CANDIDATE_PENDING_AF002` 行；AF-001 的拒绝行仍保留在原结果中，不会被删除或重评。

每个 fold 记录发布 view 输入行、有限标签与分数的评价行、发布 view 内特征缺失、
标签缺失、IC、Rank IC、ICIR、Rank ICIR 与方向一致率。coverage 的分母是该 fold
已发布 view 的输入行，名称为 published-view evaluation coverage；成员网格按年分母
不在已批准 view manifest 中，因此不将它伪造成逐 fold 指标。

行业和市值字段不在批准的 Alpha158-only view schema 中。每个 fold 固定记录
`NOT_AVAILABLE_IN_APPROVED_VIEW`，不补取或推断暴露。

一个因子必须在四个 folds 均有至少 30 个定义日、每 fold 发布-view coverage 至少
0.5、至少 75% folds 的平均 Rank IC 为正，并且四 fold 平均 Rank IC 为正，才为
`STABLE_CANDIDATE`。其余为 `REJECTED_NO_STABLE_SIGNAL`。

稳定候选两两计算日内横截面分值 Pearson 相关的日均值、日 IC 与日 Rank-IC 时间
序列 Pearson 相关，以及 top-20% score proxy（同分全保留）的逐日 Jaccard overlap。
前三项按绝对值计算；任一阈值达到 0.8、0.8、0.8 或 0.7 时连边成簇。任何未定义
关系也 fail-closed 地连边。使用连通分量，每簇按平均 fold Rank IC 降序、alpha_id
升序保留唯一代表，至多八个。top-score proxy 只是重叠诊断，不代表持仓、交易、收益
或回测。AF-001 被拒绝的六项会原样携带进 AF-002 机器结果和淘汰理由，不会消失。

受限脚本在干净提交上执行一次：

```bash
sudo bash scripts/v2/run_af002.sh
```

运行器会重新校验 DEV-001、AF-001、view、target 和配置绑定，并将结果写入
`/srv/quant-v2/development/af002/results` 的内容寻址路径。结果发布后不得改写 folds、
阈值、公式或输入 identity。`FORMAL_PIT_STATUS=BLOCKED_DATA`、
`FORMAL_RESEARCH_STATUS=BLOCKED_DATA` 与 `CSI500=NOT_STARTED` 始终不变。
