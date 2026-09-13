# V2-NEXT-02 readiness matrix（实现前）

起点：`2a803aa41ad9267842f06711df6e50c0e773b1ba`，当前工作区干净，无回退。以下是本轮全部真实前提缺项；不要求无关的全市场执行资格、成本或组合基准通过。

| 前置条件 | 已有事实/依据 | 本轮判断及最小缺项 |
| --- | --- | --- |
| 快照与解压树 | `configs/v2/datasets/qlib_cn_community_v1.yaml`固定archive `eccf69b7…7e`、release manifest `bf829907…fe2e`；之前用户释放的成员元数据报告tree `a826df48…6c93f` | 身份线索已知，未重新读取sealed；新授权需绑定实际开发源文件/树验证证据，不能只复制状态 |
| 价格/factor | 注册为adjusted；`qlib_semantics.py`定义源代码语义捕获 | 新视图所用字段含义、单位、factor/复权处理及对应证据身份需明确；不擅自选择原价或复权价 |
| train/valid日期 | evaluation配置只有研究总范围2015-01-01至2026-09-10 | 缺精确训练/验证起止日期、标签允许截止日及隔离范围 |
| 成员 | 原成员文件SHA `00380260…074c`；5个终点派生修正，见已结案审计文档 | 缺获准采用的成员版本、按T时点取成员的规则及证券—日期白名单；局部修正不是完整资格 |
| feature/warm-up | 正式模型配置仅命名Alpha158 | 缺具体字段/表达式、处理器、最大回看session数、预热起点、缺特征处理规则 |
| label/依赖 | 正式配置有两轨道、20-session horizon和20-session purge/embargo | 缺单个DEV_SMOKE选用轨道、标签价格字段、精确起终偏移/公式、训练和验证标签依赖上限及缺标签策略 |
| exporter授权 | 用户允许在范围和权限明确批准后导出；本轮未授权任意sealed数据释放 | 缺上述完整scope的批准身份、源文件白名单、可信证据/授权目录、执行账号与输出权限；CSI500禁止导出 |
| 模型配置 | 正式仅Linear/LightGBM、20种子列表 | 缺独立DEV_SMOKE的一个种子、Linear选项、LightGBM完整超参/轮数、预处理配置；不以SDK默认值猜真实参数 |

本轮可独立完成：供应商无关、哈希绑定的受限使用schema、仅合成源的安全导出器、独立开发运行器、合成E2E及负向测试。真实Qlib→规范化开发源适配、真实视图和真实DEV_SMOKE在完整scope获准之前不执行，也不声称已实现真实Alpha158装配。合成fixture的日期、字段、标签和模型参数只定义工程测试，不填补真实合同空项。

正式数据资格保持`BLOCKED_DATA`；正式封存测试保持`NOT_STARTED`。现有SealedBaselineRunner继续拒绝执行。63日结案不重开。下一步真实使用只需一次性补齐上表的受限scope与批准证据，不需要Tushare token或付费来源。
