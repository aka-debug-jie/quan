# Issue 009 运行器加固与后续证据边界

日期：2026-09-11。分支：`codex/issue009-runner-hardening`。
基线：`d70e4da91f53800ceb3e58496e2d91fb7941c6fe`；本次证据绑定工作树源文件哈希，不冒称已经提交的代码。

## 判定

- 本轮运行器工程验收：`PASS_SYNTHETIC_ONLY`。
- Issue 009 真实研究验收：仍为 `BLOCKED_CONTAMINATED` / `INVALID_RESEARCH_RESULT`。
- 未运行真实 locked test，未创建新 precommit，未开始 Issue 010–012。
- 原冻结 universe、策略、参数网格、成本配置、时间划分、基准及 V2 合同均未修改。

## 已实现

1. `research_json.py` 显式处理 date、带时区 datetime（转换 UTC）、Decimal、Enum、Path 和 NumPy 标量。未知类型、非字符串 key、naive datetime、非有限 JSON 数字直接失败；不再以 `default=str` 静默转换研究记录。
2. `research_result.py` 定义严格、版本化的 fold、step、execution plan、prepared publication 和 published result 模型。拒绝缺字段、多字段和类型强转，检查曲线日期/哈希、成交数量、Decimal 金额、OOS 汇总、结论与冻结布尔条件的一致性。最终 `result.json` 可直接读回验证，包含自校验的 `result_id`。
3. 不改变指标计算定义。仅允许指定比率字段用 `POSITIVE_INFINITY`、`NEGATIVE_INFINITY`、`UNDEFINED` 明确表示非有限结果，不输出非标准 JSON 的 NaN/Infinity。
4. 原子 claim 后、数据文件哈希读取前冻结执行清单。每完成一个配置即保存 step，再计算下一个。6 个 walk-forward folds 的跨 fold 比例在聚合前暂存 0，完整结果根据全部实际回报重新核对；单 fold 保存最终比例。
5. 保存完整 prepared 结果后才逐项写 registry、发布 final。registry 绑定 precommit、执行清单哈希、schema 及 evidence scope。只有全部预声明项及其哈希一致才能发布。
6. 异常追加到 `failures/<sha256>.json`，保留异常类型、函数/行号、阶段和已完成检查点哈希，不覆盖先前失败，不将异常输入值或完整本机路径写入凭据。claim 凭据写入失败也保留占用状态。
7. 固定实际研究的 claim authority 为仓库 `artifacts/issue009`。create/verify 均拒绝与已消耗的 2024-01-02 至 2026-09-09 重叠的 locked interval，不能靠换输出目录、代码版本或 precommit ID 重跑。
8. 修复合成压力测试实际暴露的 Decimal 边界：仅在可买金额因舍入导致超支时向下移动一个可表示单位，随后重新计算原成本并检查非负现金。未改变费用参数、容差或基准权重；有最低佣金及比例佣金的聚焦回归。

## 恢复合同

新命令 `quant backtest recover-publication` 仅接受 `SYNTHETIC_ENGINEERING_ONLY`：

```bash
uv run quant backtest recover-publication \
  --run-directory <合成attempt目录> \
  --expected-sha256 <已固定的prepared文件SHA-256> \
  --registry-root <合成registry目录>
```

它只验证并发布完整已存结果，不打开行情、不调用模拟器、不重新计算、不补跑缺项。
缺少 prepared、步骤缺失、身份不符、哈希冲突均失败。重复发布同一内容幂等。
该加固阶段完成时真实研究恢复仍未授权。其后用户另行批准的专用 V3
受控恢复以 `ISSUE_009_CONTROLLED_RECOVERY_CONTRACT_V3.md` 为唯一授权来源；
通用恢复接口仍不接受研究结果。

V3 已将双构建、独立发布凭据和纯机械恢复规则列入事前合同；仍不能仅现场重算
待恢复文件的哈希然后声称已独立认证。

## 本轮验证与证据

使用仓库 `.tools/uv/uv`、`.venv` Python 3.11.15，所有命令带 `--offline`：

```bash
uv run --offline ruff check .
uv run --offline ruff format --check .
uv run --offline mypy src
uv run --offline pytest --cov=quant_stack
```

Ruff、格式、strict mypy 全部通过；完整测试 **144 passed**，语句/分支合并覆盖率 **73.21%**。
其中新增 18 项加固测试。覆盖率不是研究有效性证明。

本地证据根：`artifacts/issue009_hardening/validation-LkNVFvs8/`。

- `junit.xml`：全部测试结果。
- `coverage.json`：机器可读覆盖率。
- `fixtures/test_synthetic_full_pipeline_r0/reproduction.json`：合成输入哈希、全部源文件哈希、冻结实验配置哈希及两次输出哈希。
- 同目录 `first/`、`independent-rebuild/`：分别完整计算、落盘的 16 项结果及 registry。

两次独立目录输出 SHA-256 均为：
`528ed6fa23be4f0e0c61eeada2d1364974484676f38c8d227c117d0f4600f39e`。

合成 E2E 使用纯合成价格、真实 trailing features、权重策略、T+1/T+2 模拟器、冻结成本、月度等权基准、6 folds、5 neighbors、2 个端点压力测试、分类与持久化。只替换数据载入边界；禁止 socket 网络连接。另验证正超额收益的检查点、部分失败、全量计算后 registry 失败、无重算恢复、篡改拒绝及 raw panel 不变。
这是运行器工程证据，不是实际 ETF 业绩，也不是实际数据适配层端到端重验。

## 原 V2 历史不变

仍保留 `docs/ISSUE_009_LOCKED_TEST_RESULT_V2.md` 及原 precommit。
原目录：`artifacts/issue009/locked_runs/d1c3c371864885134f4a733cebdc09b0fedcd2ca69ad7a8a9c1898c4374fe7c6/`。

- `attempt.json` SHA-256：`ee0a73f596b7dfc79892c919526f1fa5845c3e40325726d6804c35dc4af1195e`。
- `failure.json` SHA-256：`f363c065c07ed96e44b5136326c9b6773d6e5114d2ca5c4092af1ba3734a7820`。

本轮重新核对，均与原记录一致。原运行没有完整检查点，因此不能机械恢复正式结果。
“已消费”是本项目现行协议的执行判定，不代表已证明存在看结果后调参。

## 后续决策状态

需要新的、访问数据前冻结的研究协议，明确：

1. 2026-09-09 后真正未使用观察的 locked 起止日、观察长度和最后信号日；不能将旧区间重新包装成独立 holdout。
2. 旧区间在后续训练/选择中的角色；不得默认为可用。
3. 新数据快照与重新确认的 D0 身份、代码与配置哈希、完整运行集合、唯一 claim authority、失败和发布恢复规则。
4. 在不依结果改参数的条件下，完成全部 walk-forward、压力测试、基准比较、独立重建和正式分类；没有优势也是合法研究结论，不能以盈利为工程验收条件。
5. 现有引擎是 causal-adjusted accounting 加 raw fill audit，不等于已实现真实 raw 份额/现金公司行为账本；任何会计模型变更必须另行写入研究合同，不能称已证明数学等价。

上述选择没有由本轮代码自动决定。之后的明确用户授权和 V3 合同取代此处的
“尚未授权”状态，但不修改本报告记录的加固时点事实，也不修改旧 V2 结论。
