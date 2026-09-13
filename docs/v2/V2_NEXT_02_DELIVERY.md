# V2-NEXT-02交付：受限开发路径

起点`2a803aa41ad9267842f06711df6e50c0e773b1ba`，未回退或重写历史。本轮实现范围是规范化**合成**开发源的完整工程路径；真实CSI300规格/授权不齐，不导出真实视图、不执行真实DEV_SMOKE，不以默认参数填空。

| 状态 | 结果 |
| --- | --- |
| IMPLEMENTATION_STATUS | SYNTHETIC_E2E_VERIFIED：合同、证据loader、最小导出、独立DevBaselineRunner及负测完成 |
| REAL_DATA_VIEW_STATUS | NOT_EXPORTED_MISSING_SPEC_AND_AUTHORITY：完整缺项见readiness matrix；真实Qlib/Alpha158适配未启用 |
| DEV_SMOKE_STATUS | 合成Linear/LightGBM及复现通过；真实开发冒烟NOT_RUN |
| FORMAL_RESEARCH_STATUS | 原资格BLOCKED_DATA；CSI500封存测试NOT_STARTED；原SealedBaselineRunner仍拒绝执行 |

## 合同、输入与实现

- [完整前置条件matrix](V2_NEXT_02_READINESS.md)：在实现前一次性列出已知身份与全部缺项，没有逐项补完后再追加研究授权问题。
- [独立受限使用合同](LIMITED_DEV_USE_V1.md)。真实scope草案：`configs/v2/development/limited_dev_v1.yaml`；独立DEV_SMOKE草案：`configs/v2/models/dev_smoke_v1.yaml`，未定义的字段明确保留null。
- `dev_contract.py`：严格schema、实际文件SHA复验、供应商无关源/范围证据；可信UsePins绑定contract/evidence/view。任何运行请求不能替换这些部署pin。真实授权服务及privileged exporter不由本轮虚构。
- `dev_view.py`：只为T时成员的正式样本展开必要lag/label依赖；不因T+h成员变化或缺失标签删掉T预测资格。路径遍历、symlink、hardlink、CSI500/真实源标签和sealed根均拒绝。
- `dev_baseline_runner.py`：独立于sealed基线；仅训练数据拟合标准化，实际session标签依赖校验，固定单seed Linear/LightGBM CPU训练、验证预测、MSE/IC、pickle往返、原子结果持久化及重复复现。没有组合指标，未定义MSE/IC为null；completion缺失/不匹配不能载入为完成。

模型家族未扩展。合成runner使用sklearn LinearRegression和LightGBM LGBMRegressor，原Qlib两轨道/20种子协议、完整Foundation Gate和旧实验结果不修改。新接口的供应商无关“源字节/范围验证”不冒充真实市场raw价格对账；旧Tushare门报告不被改名或升级。

## 验收

- Ruff、格式、mypy完整通过。
- 完整离线默认pytest **364 passed**；新增证据/导出单元测试29项包含在内。
- 原V2环境冒烟 **5 passed**；新增开发runner/safety **21 passed**，由V2 CI单独显式调用，非默认5项冒烟替代。
- 默认coverage **71.25%**；追加独立V2 runner覆盖后 **74.16%**。没有删测试、减弱旧断言或扩大skip。完整pytest仅运行合成单元测试，未执行旧locked研究实验。
- 负测覆盖伪造QUALIFIED、源/树/范围/版本不匹配、同scope重哈希改值、未批准view、链接/越界、按T成员投影、warm-up/标签越界、训练标准化隔离、缺未来标签仍预测、模型重载、输入/代码/结果漂移、写入中断、completion失败及未定义指标伪装0。

完全合成的可查看示例：`artifacts/v2/v2_next_02/synthetic_example/`，包括源、contract/evidence、view、两个模型、预测、指标和完成指针；使用测试fixture的固定1701 seed，不代表真实市场结果。状态与身份报告：`artifacts/v2/v2_next_02/4d4ca1fb63f0bb913865593b5eb9fa7cd46c04eaed281220c4a7cfb4da0cb851.json`。

合成scope SHA：`b6ae1b1ca67568ba3cfcf0b47b0736cd5e985bfae2bcd730fe44ac3b4b896ed9`；evidence SHA：`9689d477871ec79f861ce97d9df378ba797513744402dc772f250a01fd58812a`；view SHA：`95da1ca585675d5fb4d4a3c3483e45f0c28ad926a562d8edb774869deb306456`。测试自身每次从临时目录独立生成输入，不依赖该示例或任何真实artifacts。

## 一次性剩余真实输入

需同时补齐并批准：精确train/valid及标签依赖边界、CSI300证券—日期/成员版本、字段与价格factor证据、Alpha158/预处理/预热规格、精确标签轨道/公式/偏移、单seed完整模型参数、规范化源文件白名单及实际身份、exporter/operator可信授权和输出权限。没有要求全市场执行资格、组合成本基准或Tushare token通过；也不会为这次开发路径重开63日审计。

拿到这些定义后还需按其接入/审阅真实规范化适配器，不能仅修改data_kind绕过当前SYNTHETIC护栏。该真实接入不在本轮自动执行。代码提交及其对应远端CI结果由最终回复和本机`artifacts/v2/v2_next_02/`的completion记录给出。本任务完成后停止，不开始多种子、外部检验、收益声明、timer或实盘。
