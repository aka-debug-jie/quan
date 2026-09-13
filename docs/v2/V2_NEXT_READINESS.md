# V2-NEXT-01：CI与研究基线环境验收

本轮仅验收工程环境。63日免费审计保持结案；V2-003/V2-004等原有`BLOCKED_DATA`不变。没有真实市场训练、sealed读取/释放、V1修改、冻结参数修改或新运行器实现。

## 指定CI失败

[run 34754026731](https://github.com/aka-debug-jie/quan/actions/runs/34754026731)，提交`f92b997c5afc5d77ebc0c86e855fcfc5f2705b04`，`checks`任务失败。以下四个测试位于`tests/test_v2_szse_audit_bridge.py`：

| 准确测试名 | traceback最终异常 |
| --- | --- |
| `test_actual_pdf_matches_original_and_exports_only_summary` | `FileNotFoundError: [Errno 2] No such file or directory: '/usr/bin/pdftotext'` |
| `test_client_has_no_sudo_and_rejects_engine_drift` | 同上，缺`/usr/bin/pdftotext` |
| `test_pdf_page_limit` | `FileNotFoundError: [Errno 2] No such file or directory: '/usr/bin/pdfinfo'` |
| `test_frozen_host_runtime_has_closed_imports_and_identical_results` | 同上，缺`/usr/bin/pdfinfo` |

调用链分别经过`szse_issuer_supplement.load_claims → subprocess.run → Popen`或桥接PDF页数检查后进入`Popen`；完整原始日志已读取并归档。原始GitHub run为Ubuntu24.04.5、Python3.11.15、uv0.12.13。本机原环境已装Poppler，而CI工作流只安装Python依赖，未声明Poppler系统依赖。

干净复现使用`git archive f92b997`、Ubuntu24.04.4容器、Python3.11.15、uv0.12.11及未改变的`uv.lock`，复现完全相同的4 failed/6 passed。其与GitHub镜像不同之处是精简容器也没有系统Python、时区数据库和Git：补Poppler后暴露`/usr/bin/python3`缺失；全套检查又暴露`Asia/Shanghai`时区和`git init`不可用。这三项属于容器差异，不能归因于原始GitHub失败。工作流显式声明`poppler-utils python3 tzdata git`；补齐PDF及系统Python后桥接测试10/10通过。修复不删除测试、不减弱断言、不增加skip。

## V2专用环境

独立CI任务显式运行`uv sync --locked --group v2`，验证`pyqlib==0.9.7`、`lightgbm==4.5.0`、`xgboost==2.1.4`的安装元数据及实际模块版本。专用测试文件由CI显式执行，不依赖默认环境恰好装有这些可选包。

合成MultiIndex DataFrame经Qlib `DataHandlerLP.from_df`和`DatasetH`进入真实`LinearModel`/`LGBModel`训练与预测，检查有限且非恒定预测、优于合成目标均值基准，以及模型保存/重新加载后的逐项精确一致。模型结果只写pytest临时目录；Qlib指标记录被替换为内存收集器，不启动市场实验或MLflow服务。网络连接和DNS调用在测试中直接拒绝。合成fixture参数不是冻结市场研究配置。

## 实现与权限检查（本轮不修改）

| 项目 | 判断 |
| --- | --- |
| `foundation_gate.py`必需门聚合 | 已实现名称/状态聚合，但并非完整证据验证器；会接受调用方自报`QUALIFIED`，CLI计算哈希也没有验证业务语义、来源权威性或研究范围。 |
| `tushare_raw_reconciliation` | 必需门名已存在，`tushare_pro.py`有原始抓取；尚无对应完整对账证据生产者/专用验证器。不能因此要求用户购买数据或申请token。 |
| `baseline.py` fixed runner | 占位、拒绝执行；尚未实现真实基线训练。 |
| baseline precommit | 绑定import、模型配置、代码和同源PIT结构报告，未绑定完整Foundation资格证据；成员内部结构通过不代表官方PIT资格。 |
| 真实研究使用权限与数据质量 | 未验证、未批准；工程合成冒烟通过不改变任何数据资格。 |

下一任务方案：用供应商无关的`independent_raw_market_reconciliation`语义接口承载版本化证据，供应商仅作元数据；每份证据绑定import/tree、universe、日期范围、源快照及判定器身份，由专用loader重验。Foundation聚合和precommit必须绑定相同完整资格证据身份，拒绝任意JSON状态直通。

受限开发视图应先用完全合成schema fixture实现运行器；后续另行批准CSI300开发范围及字段白名单，只发布新的内容寻址开发视图和最小资格摘要。CSI500继续隔离，不复制或放宽sealed目录，不以细粒度摘要泄露holdout。视图方案和权限变更本轮均不实施。

## 最终验收

- 最小系统修复后，原桥接文件10项测试全部通过；精简副本补入原提交Git元数据后，全套在网络已断开的容器内 **335 passed，85.23秒，覆盖率73.18%**。源码归档最初不含`.git`造成的提交号读取失败也已作为环境差异记录，没有修改V1测试或实现。
- Ruff、格式检查、mypy完整检查通过；`uv.lock`、冻结模型配置和全部资格/运行器实现保持原样。
- 干净V2环境 **5 passed，6.18秒**：三个锁定版本及两个真实Qlib合成模型round-trip均通过；安装阶段与禁止联网的测试阶段分离。
- 证据保存于本机忽略目录`artifacts/v2/v2_next_01/`，含原始CI日志、干净复现前后traceback、环境差异、安装日志、静态检查、完整coverage和V2冒烟结果。远端结果以本任务最终回复所列修复提交及其GitHub run为准，另归档对应run元数据。

本轮验收完成即停止。批准研究范围、修复资格证据绑定及实现开发基线运行器属于下一任务。
