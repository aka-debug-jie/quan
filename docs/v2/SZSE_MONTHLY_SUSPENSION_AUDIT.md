# 深交所月报缺失交易日审计

本实现仅用已归档的深交所公开月报，离线解析并匹配 Qlib 缺失日期。
不购买数据、不调用 Tushare/BaoStock、不训练模型、不修改历史证据或成员区间。

## 公开证据与当前状态

索引：`artifacts/v2/szse_monthly_evidence/2140ec9a8ca8e17a542a7d8337ed3d672f655c86acf3446d82d8bc691b662ac1.json`。
2015-01 至 2026-08 的 140 张表全部通过 SHA-256、标题月份及五列结构校验。
共 8,001 条记录：6,693 条开放区间，1,308 条含明确复牌时间；261 条为盘中开始，
其中 16 条时间写作“盘中即时”。本批表中没有开始与复牌日期相同的记录；解析器另有当日停复牌回归测试。

`sz000540` 在 2017-08 月报的第 41 行（包括表头）记录
`2017/08/21 09:30` 开始停牌，复牌为 `9999/12/31 00:00`。
原始表 SHA-256 为 `dc82301e7818c6d7271c154e5c34d8c8a2fdc87cbdc31e19eb53b994d1c3e009`。

索引中的旧 `/tmp` 路径仅保留作历史抓取元数据。读取一律使用索引旁的
`raw/<table.sha256>/body.html`，不依赖旧临时目录。

用户已回传固定脚本实跑统计：342 个区间、8,093 个缺失日期均已完成逐日匹配。
完整覆盖 203 个区间，部分覆盖 133 个，无匹配 6 个，冲突 0 个。
2,066 日获得完整停牌证据（25.53%），6,027 日仍未解释；缺口 gate 为 `BLOCKED_DATA`。
这表示本轮审计执行完成，数据资格尚未通过。

统计来源为用户回传的标准输出；本地已复核两个代码文件和公开索引的 SHA-256，
并确认区间与日期计数守恒。开发用户未读取受限完整报告，因此未独立复核逐日残余内容或报告文件哈希。
受限报告为：
`/srv/quant-v2/sealed_holdout/artifacts/v2/free_suspension/szse_monthly_verification/b31fc67f7707cb728f1606b45ce909e0d1907991e62075be050b95a3ad186873.json`。
每日审计内容 SHA-256 为 `99013d70b4ab14d76c9fd1e511edfac9418cfb6ca113474de1cab654f1f57c02`。
本地回传摘要归档：`artifacts/v2/szse_monthly_run_receipts/6f1cf5dee2a5fc1ad342cefaec2cf96023faaaae937305303eb410c0367a9ac8.json`。

仅从汇总数字无法确定 6,027 日残余的具体原因；不能通过延长开放区间或改写成员区间使 gate 通过。
原有沪市审计及其证据保持不变。CSI 官方调样日期仍未核实，成员 gate 保持 `BLOCKED_DATA`。

## 日期语义

- 使用交易所本地日期时间，保留原始时间文本；严格尝试 UTF-8，失败后用 GB18030。
- 首日停牌时间晚于 09:30 或写作“盘中即时”，首日不能解释完整缺失交易日。
  未知盘中时间没有伪造为已知时刻，内部日期与 `start_is_intraday` 一起解释。
- 明确复牌时间给出已闭合区间。完整覆盖不含复牌日，即使复牌字段写作 15:00 也保守排除。
  明确闭合区间可跨月；这是事后证据匹配，不宣称当时已经可以获取该信息。
- `9999/12/31 00:00` 仅是开放区间标记，覆盖与所属自然月取交集。
  不把前一个月的开放记录自动延续到下一月。
- 同一事件有明确复牌时间时截断开放记录。后续同证券的新停牌或实际复牌事件也会截断旧开放记录，
  防止旧占位记录掩盖中间或之后的数据缺口。
- 同一事件的明确复牌时间相互不一致时保留冲突。缺失日恰为盘中开始或实际复牌日时，
  记为 `TRADING_BOUNDARY` 冲突，不能用另一条覆盖记录强行判为完整停牌。
  该冲突要求复核，并不等同于已验证当日确有价格成交记录。

## 固定的受限数据执行入口

由用户在主机执行，不调整原始数据权限：

```bash
sudo bash /media/hgdl1012/84f6bd42-d506-47ff-8bf3-7b354ba37618/media/hgdl1012/program/quan/scripts/v2/verify_szse_monthly.sh
```

也可由已有正确访问权限的 `quant-eval` 账户执行同一脚本。
脚本使用 `/srv/quant-v2/results/runtime/bin/python`，只读固定的公开索引、候选计划及每日审计。
计划文件内容哈希必须匹配文件名，计划必须绑定每日审计的 SHA-256；所有深市缺失日期必须被计划恰好分配一次。
另要求恰有 342 个区间和 8,093 个缺失日期。失败时不产生可通过的匹配结果。

新增报告位于：
`/srv/quant-v2/sealed_holdout/artifacts/v2/free_suspension/szse_monthly_verification/<SHA256>.json`。
每次输出不可变，不覆盖已有报告。标准输出只含统计、输入/代码哈希和报告路径。
有残余时仍保存完整报告，然后返回退出码 1；退出码 0 只表示此次缺口 gate 通过。

报告包含：

- `interval_counts`：`FULL`、`PARTIAL`、`NO_MATCH`、`CONFLICT` 四类区间数；有冲突的区间优先归入冲突。
- `covered_sessions`、`unexplained_sessions`、`conflict_sessions`；三者之和等于 `missing_sessions`。
- `results`：每个候选区间及逐日分类、来源月份、HTML 行号、原始表 SHA-256、官方 URL、停复牌时间。
- `residual`：全部未解释或冲突日期及证据；未知原因不被自动改成停牌。
- `gap_gate` 与 `membership_gate`：前者可因全覆盖成为 `PASS`，后者仍为 `BLOCKED_DATA`。

开发用户无权读取 sealed holdout，因此本次不代替用户执行 sudo，不读取或复制受限原始数据。
只需回传标准输出统计即可确认真实匹配计数；逐日残余保存在受限目录供授权用户复核。

## 本地公开解析

```bash
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src .venv/bin/python -m quant_stack_v2.szse_verification \
  --index artifacts/v2/szse_monthly_evidence/2140ec9a8ca8e17a542a7d8337ed3d672f655c86acf3446d82d8bc691b662ac1.json \
  --output-root artifacts/v2/szse_monthly_parse
```

公开解析报告含全部 8,001 条行记录，不含受限 Qlib 数据。其 `gap_gate=NOT_RUN`。

## 离线验收（2026-09-12）

- Ruff 全库检查通过，148 个 Python 文件格式检查通过，mypy 的 70 个源文件检查通过。
- 完整 pytest：246 passed；分支计入的整体 coverage 为 72.04%。
- 新增 `szse_monthly.py` coverage 为 97.56%，`szse_verification.py` 为 91.14%。
- 本次完整测试通过临时 `sitecustomize.py` 禁止 socket 连接，Numba/Hypothesis/coverage 缓存放在临时目录。
- 原有 BaoStock 可选导入改用标准库延迟导入，避免依赖安装状态导致 mypy 注释失效；没有调用或登录 BaoStock。
- 原有数据资格测试显式指定临时产物目录，避免测试向项目历史 `artifacts` 写入。
- 起始时的 7 个未跟踪沪市文件逐一哈希检查，全部保持不变。

完整测试命令（`task_qa` 应指向已归档验收目录，含 `offline_guard/sitecustomize.py`）：

```bash
PYTHONPATH="$task_qa/offline_guard:src" PYTHONDONTWRITEBYTECODE=1 \
NUMBA_CACHE_DIR=/tmp/quant-szse-numba HYPOTHESIS_STORAGE_DIRECTORY=/tmp/quant-szse-hypothesis \
COVERAGE_FILE=/tmp/quant-szse-coverage .venv/bin/python -m pytest -q -p no:cacheprovider \
  --cov=quant_stack --cov=quant_stack_v2 --cov-report=json:/tmp/quant-szse-coverage.json
```

## 残余诊断与补证（2026-09-12，后续）

公开表逐行检查发现：全部 8,001 条记录的停牌开始年月都与月报年月相同；
同一证券、同一开始时间没有跨月重复记录；1,308 条明确复牌记录中有 174 条复牌时间跨月。
这批月报不能被当作逐月确认仍在停牌的完整存量清单。
这些公开结构事实不能独自解释原报告剩余 6,027 日的原因。

新增 `szse_residual.py` 和固定脚本 `scripts/v2/diagnose_szse_residual.sh`：

```bash
sudo bash /media/hgdl1012/84f6bd42-d506-47ff-8bf3-7b354ba37618/media/hgdl1012/program/quan/scripts/v2/diagnose_szse_residual.sh
```

脚本只读取已指定的 `b31fc67f...` 报告和原公开索引；先验证报告文件名哈希、
索引绑定及原解析器/验证器源码哈希，逐一重放残余日期原分类，检查恰有 6,027 日。
诊断不会修改月报、原审计报告、原分类、停牌覆盖边界或两个 gate。

标准输出包含年份统计、线索分类、原来的无匹配区间，以及按残余日数排序的前 20 个补证任务。
完整任务保存在受限目录 `artifacts/v2/free_suspension/szse_residual_diagnostics`，
包括最近的前后公开事件及其原始表哈希/行号/链接。任务只按原候选区间内部的相邻缺失交易日合并，
遇到已解释日期或线索分类变化即断开；不使用自然日相邻推测交易日历。

线索分类只决定下一步检索方向：

- `PRIOR_MONTH_OPEN_NEEDS_CONTINUATION_PROOF`：之前月份有开放记录，缺少当前日期的完整覆盖，需要另找持续停牌或实际复牌公告。
- `NO_SYMBOL_RECORD`：现有月报没有该证券记录。
- `NO_EARLIER_SUSPENSION_RECORD`：只找到缺失日期之后开始的停牌记录。
- `OUTSIDE_ARCHIVED_MONTHS`：日期不在已归档月份内。
- `OTHER_UNEXPLAINED`：其他未解释情形。
- `EXISTING_CONFLICT`：原报告已有冲突，需要复核。

这些标签不等同于真实缺失原因，`newly_explained_sessions` 固定为 0。
用户回传诊断摘要后，才能按具体区间有针对性地查找免费公开证据。

已先对用户最初给出的 `sz000540` 实例完成有界检索，归档三份巨潮资讯发行人公告：

| 发布日期 | 公告链接 | 证据作用 |
| --- | --- | --- |
| 2017-10-21 | https://static.cninfo.com.cn/finalpage/2017-10-21/1204057238.PDF | 第1页确认2017-08-21开市起停牌，并披露持续停牌事项 |
| 2018-12-29 | https://static.cninfo.com.cn/finalpage/2018-12-29/1205700411.PDF | 第3、12页披露拟定/安排2019-01-02复牌；不单凭计划用语认定已实际复牌 |
| 2019-10-18 | https://static.cninfo.com.cn/finalpage/2019-10-18/1206990903.PDF | 第3页回顾2017-08-21停牌，并明确股票于2019-01-02开市起复牌 |

PDF、提取文本和抓取索引保存在 `artifacts/v2/szse_issuer_notice_evidence/`。
这是发行人披露证据，与深交所月报来源类型分开保存。
可以据此继续审查该事件的有界区间，复牌日2019-01-02本身不属于完整停牌日。
尚未将这些公告与受限残余逐日匹配，未报告新增覆盖数，也不提升 PIT 成员资格。

后续诊断验收：Ruff、格式与 mypy 全库通过，完整离线 pytest 为 253 passed；
总 coverage 为 72.36%，新诊断模块 coverage 为 94.70%。
独立复核无阻断性发现。验收产物：`artifacts/v2/szse_residual_qa/ab6a0606d6d57397157696cb088bf69ff75425161f245a71b231f7a190977ac7`。
真实诊断结果待用户运行固定脚本后回传，仍未新增任何已解释日期。

## 首批发行人公告补证

用户回传的残余诊断摘要已核对代码哈希与计数守恒：6,027 日分布于 93 只证券、139 个任务。
其中 5,906 日为 `PRIOR_MONTH_OPEN_NEEDS_CONTINUATION_PROOF`，19 日为
`NO_EARLIER_SUSPENSION_RECORD`，102 日为 `NO_SYMBOL_RECORD`。
这只是检索线索分类；没有直接把 5,906 日改成停牌。

本批先审核四个最长候选区间。原始 PDF 的相关页面均已目视核对，并使用
`/usr/bin/pdftotext -layout` 离线重提取核验确切原文锚点。

| 证券 | 公告确认的停牌日期 | 事后确认的复牌日期 | 用户回传的本候选残余日数 | 主要原始公告 |
| --- | --- | --- | ---: | --- |
| 000540 中天金融 | 2017-08-21 | 2019-01-02 | 323 | https://static.cninfo.com.cn/finalpage/2019-10-18/1206990903.PDF 第3页 |
| 002739 万达电影 | 2017-07-04 | 2018-11-05 | 307 | https://static.cninfo.com.cn/finalpage/2018-11-27/1205631895.PDF 第1、2页 |
| 002129 中环股份 | 2016-04-25 | 2017-11-29 | 283 | https://static.cninfo.com.cn/finalpage/2017-12-01/1204180194.PDF 第1页 |
| 002252 上海莱士 | 2018-02-23 | 2018-12-07 | 190 | https://static.cninfo.com.cn/finalpage/2019-10-24/1207008580.PDF 第8、10页 |

四个候选残余日数合计 1,103 日。这是用户摘要所列范围，不是本轮已完成的受限逐日匹配计数。
中环股份的候选残余截止于2017-06-29，而公告复牌日期为2017-11-29；候选末日并不被当作复牌日。

万达电影的主要说明文件未列证券代码，另外绑定其发行人同名的原始复牌提示公告
https://static.cninfo.com.cn/finalpage/2018-11-05/1205579190.PDF
用于核对证券代码002739和发行人名称。该提示公告的“将于”表述不作为实际复牌证据；
实际复牌采用2018-11-27董事会说明的事后表述。

已审核清单：
`artifacts/v2/szse_issuer_notice_evidence/bfa6639ef00fffda27feb41ed9d366492bfdc6deffc976f0541179dc01c1ed88.json`。
PDF 均按原始字节 SHA-256 命名，抓取记录、文字提取和旧证据并存，未覆盖旧文件。
该清单是人工审核的证据契约；正文锚点核验不等同于自动理解任意公告。
扩充清单仍需逐份核对证券身份、事件关联、持续性及真实复牌措辞，不能只填日期。

固定受限执行入口：

```bash
sudo bash /media/hgdl1012/84f6bd42-d506-47ff-8bf3-7b354ba37618/media/hgdl1012/program/quan/scripts/v2/supplement_szse_issuer.sh
```

脚本只读取指定原始月报审计和已审核清单；不调整原始权限，不联网、不登录、不训练模型。
需主机已有 `/usr/bin/pdftotext`；缺少时失败，不使用未经复核的缓存文字冒充 PDF 重提取。

新报告写入：
`/srv/quant-v2/sealed_holdout/artifacts/v2/free_suspension/szse_issuer_supplement/<SHA256>.json`。
原月报报告保留，新报告的来源类型为 `SZSE_MONTHLY_PLUS_ISSUER_NOTICES_RETROSPECTIVE`。

补证规则：

- 为避免从“停牌日期”推断当日具体时间，本次新增覆盖从停牌次日开始；原月报已解释的首日保持不变。
- 实际复牌当日不纳入完整停牌覆盖，发现其与原完整停牌覆盖矛盾则记录冲突。
- 只把 `UNEXPLAINED` 改为 `ISSUER_CONFIRMED_SUSPENDED`；既有冲突不被补证覆盖。
- 同一事件出现不同实际复牌日期时，相关日期记录为冲突。
- “拟于”“将于”“预计于”等计划用语不被实际复牌锚点校验接受。
- 每日证据保留 PDF 哈希、官方链接、页码、原文锚点及提取文字哈希。
- 两种已解释来源分别保留，PIT成员 gate 原样继承，不能因缺口减少而升级。

标准输出包括新增解释总日数、逐证券新增日数、覆盖/残余/冲突日数和区间统计，
以及前20个剩余候选的边界与残余日数，便于继续补证。
`remaining_first` 至 `remaining_last` 仅为残余日期包络，不声明其中每个交易日均缺失。
存在残余时退出码1为预期；完整新报告仍会保存。

实际复牌锚点还校验所在句的前置计划/条件/否定语境，避免截短锚点掩盖计划用语。
这些校验只服务于人工审核清单，不作为无人工复核的通用公告语义分类器。

首批公告补证最终离线验收：274 passed；Ruff、格式、mypy通过；
整体coverage 72.72%，补证模块coverage 90.13%。
独立复核发现的锚点前置计划语义问题已修复并复核通过。
验收与原PDF页面预览：`artifacts/v2/szse_issuer_supplement_qa/a5a9ae40e5a33c832ccf6556ea7d9f5a80c5b7a49e682d3fd289217ba1dffe59`。
真实新增覆盖数仍待用户固定脚本回传，不把1,103个候选残余日直接记为已解释。

## 首批公告补证实跑回传

用户已回传首批补证实跑统计。开发侧核验补证代码和清单哈希与当前文件一致，
并核对日期、区间、逐证券新增计数守恒；未直接读取受限完整报告或独立核验其文件哈希。

- 本批新增解释1,103日：000540为323日、002129为283日、002252为190日、002739为307日。
- 深市累计覆盖3,169 / 8,093日（39.16%），残余4,924日，冲突0日。
- 区间统计：FULL 207、PARTIAL 129、NO_MATCH 6、CONFLICT 0；合计342。
- 缺口gate及PIT成员gate均仍为BLOCKED_DATA。
- 本次为用户实跑回传统计，已取代上一节的“候选1,103日待确认”状态；历史预估记录保留。

完整报告：`/srv/quant-v2/sealed_holdout/artifacts/v2/free_suspension/szse_issuer_supplement/9b9fa0d76a1218d962ad4e9c9f5dd41a6fdfaa6a1ad734575ff6707783989c8f.json`。
本地回传摘要：`artifacts/v2/szse_monthly_run_receipts/f7e8c87f355de58eeb1ef2b7f2a1163300000b24abc546ce01b29776f276826d.json`。

下一批优先对象来自本次输出的top_residual_tasks：002426（180日）、300104的2017年区间（166日）、
000630（137日）、000651（129日）。这里只确定补证优先顺序；尚未对这些对象新增合格证据或改写覆盖。

## 第二批公告补证准备

本批新增人工审核的两个历史事件，累计清单保留首批四条原记录：

| 证券 | 已核实停牌日期 | 事后复牌日期 | 新候选残余日数 | 官方来源 |
| --- | --- | --- | ---: | --- |
| 300104 乐视网 | 2017-04-17 | 2018-01-24 | 166 | https://static.cninfo.com.cn/finalpage/2018-04-27/1204808165.PDF 第60页 |
| 000630 铜陵有色 | 2015-03-09 | 2015-10-23 | 137 | https://static.cninfo.com.cn/finalpage/2016-04-14/1202174811.PDF 第4页 |

两条新增候选区间合计303日，仅为用户上一轮回传范围，真实新增覆盖数待受限实跑。
乐视网另一个2015-12-07开始的停牌区间不属于本条事件，不能被本次证据覆盖。

本批继续使用发行人事后肯定复牌的证据规则；补证器仅新增支持两种实际原文句式：
省略复牌日期前的“于”，以及使用“自”引出停牌起点的组合句。
原日期边界、前置计划/条件语义拒绝规则、冲突保留和成员gate规则保持一致。
增加两项肯定句与三项计划语境回归用例。
上一版源码原文按SHA-256保存在
`artifacts/v2/szse_issuer_notice_evidence/verifier_sources/35c318bdac5196895d11c1ed8bdae81a4b440504a373ca7cf6b7a95096041a04.py`。

累计六事件清单：
`artifacts/v2/szse_issuer_notice_evidence/f92a067587978322c286578299105d982d3cf8fd61aa27da725bf61f58f79cfa.json`。
六事件原始PDF均重新校验哈希和正文锚点；新增两事件的原始页面已目视核对。

```bash
sudo bash /media/hgdl1012/84f6bd42-d506-47ff-8bf3-7b354ba37618/media/hgdl1012/program/quan/scripts/v2/supplement_szse_issuer_batch2.sh
```

这是累计重算：输入仍是原始月报报告 `b31fc67f...`，不把已解释日重复追加。
输出中的 `newly_explained_sessions` 表示相对原月报2,066日覆盖的累计增量，包含首批1,103日；
本批实际新增应按新报告的 `covered_sessions` 减去已实跑的3,169计算，并一并核对冲突数。
若新两事件完全匹配且没有其他变化，候选预测是累计新增1,406日，但不能在实跑前报告为已解释。
固定脚本只新增独立不可变报告，仍由用户sudo或quant-eval执行，不调整sealed原始权限。

本轮未纳入的对象与边界：

- 胜利精密002426：找到复牌报道及公告线索，但当前获取的原始材料未满足本次发行人事后复牌规则；180日候选继续保留未解释。
- 格力电器000651：已归档2016-09-02复牌提示公告及2016年年报，但提示公告使用“将于”安排用语，未据此认定实际复牌；129日候选继续保留未解释。
- 乐视网2018-01-24的原始提示公告也已归档；本批实际复牌采用其后发布的2017年年报确认，而不是只凭当日安排。

所有下载保留原始字节、来源URL、时间、SHA-256和提取文本；未采用未满足条件的文件改变计数。

独立复核补充的句末锚点检查也已实现：复牌锚点必须包含句号，避免截掉右侧“的计划尚待批准”等语义；六条已审核原文均通过。

## 第二批实跑回传与最终验收

用户已回传固定脚本结果；开发侧核验清单与补证代码SHA-256一致，计数守恒。
未直接读取受限完整报告或独立核验其文件哈希。

- 相对首批新增303日：乐视网166日、铜陵有色137日。
- 相对最初月报累计新增1,406日，深市总覆盖3,472 / 8,093日（42.90%）。
- 残余4,621日，冲突0日。区间FULL 209、PARTIAL 127、NO_MATCH 6、CONFLICT 0。
- 两个gate仍为BLOCKED_DATA，未作PIT成员资格升级。
- 完整离线pytest为281 passed；Ruff、格式、mypy通过，整体coverage 72.73%，补证模块coverage 90.31%。

用户报告路径：`/srv/quant-v2/sealed_holdout/artifacts/v2/free_suspension/szse_issuer_supplement/e4df56b9d2dafab48582ecd68b99ef196c370dc071618885faa93052132b3deb.json`。
本地回传摘要：`artifacts/v2/szse_monthly_run_receipts/343f5ebdbc91e2e5f623ec46ab1c7628115d904012e635417ff14eea8aaab9d8.json`。
最终验收与页面复核记录：`artifacts/v2/szse_issuer_supplement_qa/ffb7627e817a277a4eededbb503782055f9e55c8781ab55ac7f880e47d4c04d5`。

## 第三批跨公告补证准备

本批新增两个已人工目视审核的事件，累计清单保留第二批六条原记录：

| 证券 | 发行人确认的停牌日期 | 实际复牌日期 | 本候选残余日数 |
| --- | --- | --- | ---: |
| 000002 万科A | 2015-12-18 | 2016-07-04 | 121 |
| 002310 东方园林 | 2015-05-27 | 2015-12-07 | 127 |

两条候选合计248日，尚不能在受限实跑前认定为新增覆盖。
万科原候选从2015-12-21开始，不代表公告停牌日期必须是该日；补证区间保守排除公告停牌首日，
从2015-12-19开始，再仅匹配原报告内真实缺失交易日。

原始证据及页码：

- 万科停牌起点： https://static.cninfo.com.cn/finalpage/2017-03-27/1203197044.PDF ，PDF第67页（印刷第66页）。
- 万科实际复牌： https://static.cninfo.com.cn/finalpage/2016-08-25/1202613500.PDF ，PDF第7页。
- 东方园林停牌起点： https://static.cninfo.com.cn/finalpage/2015-12-05/1201808593.PDF ，第1页；该文件的“将于”复牌安排不用于认定实际复牌。
- 东方园林实际复牌： https://static.cninfo.com.cn/finalpage/2015-12-10/1201824569.PDF ，第1页；这是已发生交易异常波动后发布的公告，正文明确回顾实际复牌。

停牌与复牌事实分别从两份PDF核验，使用 `start_raw_sha256` / `start_official_url` 独立绑定。
除原始PDF哈希和官方域名外，两份文件首页须有同一完整发行人名称，起点PDF须有目标证券代码；
日期和原文锚点必须位于指定页。新增记录保留起点PDF重提取文本哈希。

东方园林的实际复牌表述在编号清单中以分号结束，只有分号后紧接下一编号项时才接受；
“现将有关核查情况说明如下:”是已经核查后的报告引导语，仅精确剔除该短语再检查计划词，
其他计划、条件、否定语义仍须拒绝。该规则依旧只服务人工审核清单，不宣称自动理解任意公告。

第二批已验收源码原文快照保存在：
`artifacts/v2/szse_issuer_notice_evidence/verifier_sources/64f529001d06a5cc11ad3532a48373d416aa05ec0d52f359bfe3ae6c8d7624cd.py`。
原有各批报告、清单、源码快照和证据均保留。

累计八条清单：
`artifacts/v2/szse_issuer_notice_evidence/efb3ff91a785dc9e81ad8f6e2a0f1365c2290c6ec8adcf3b1709f37e6a3bcfa6.json`。

```bash
sudo bash /media/hgdl1012/84f6bd42-d506-47ff-8bf3-7b354ba37618/media/hgdl1012/program/quan/scripts/v2/supplement_szse_issuer_batch3.sh
```

仍以原月报报告b31fc67f...为基线累计重算。标准输出的 `newly_explained_sessions` 包含前两批已确认的1,406日。
本批实际增量应按新 `covered_sessions` 减去3,472并同时检查冲突数。
如果两候选完整匹配且没有其他变化，预计相对原月报累计新增1,654日，但实跑前不记录为已解释。
脚本只新增不可变报告，由用户sudo或quant-eval执行，不更改原始权限。

海虹控股仅获得停牌起点及其他来源的复牌线索；本轮检索未闭合满足本批规则的发行人事后复牌证据，
暂不纳入。胜利精密、格力电器的旧证据缺口也未因本批修改而自动改变。

第三批代码与证据验收：285项完整离线pytest通过，Ruff、格式、mypy通过；
整体coverage 72.82%，补证模块coverage 91.14%。
独立复核无阻断发现。验收与PDF页面复核记录：`artifacts/v2/szse_issuer_supplement_qa/549d0922808cbc3708f1864724b9149c0e3f7ed6c86fcfc67e97bb8f7bcb3ed3`。
本批真实匹配尚待用户固定脚本回传，未将248候选日记为新增解释。

## 第三批实跑回传

用户已回传第三批固定脚本结果。补证器与清单SHA-256已在开发侧核验匹配，
逐证券、日期和区间计数守恒。开发用户未直接读取受限完整报告，也未独立校验该报告文件哈希。

- 本批相对第二批新增248日：万科121日、东方园林127日。
- 相对原月报累计新增1,654日，深市覆盖3,720 / 8,093日（45.97%）。
- 残余4,373日，冲突0日。区间FULL 211、PARTIAL 125、NO_MATCH 6、CONFLICT 0。
- 缺口gate与PIT成员gate均保持BLOCKED_DATA。

受限完整报告：`/srv/quant-v2/sealed_holdout/artifacts/v2/free_suspension/szse_issuer_supplement/d924987b0764e74a0bc143b3bc9f1c9e70a5c62befbe3c9ece3a94195149c605.json`。
用户回传摘要归档：`artifacts/v2/szse_monthly_run_receipts/b0d8a1336740388b9d54b69ef1782566e07af4cd5c3b47c58b40d30fcee19852.json`。
前述248候选日待实跑状态已由本次回传确认；历史准备记录保留。

## 自动推进与完整补证队列

用户要求普通节点自动推进，仅在需读取受限报告时请求用户执行命令。
新增 `szse_evidence_queue.py`：核验完整报告内容哈希、残余唯一计数、原结果集合一致性后，
输出全部残余候选的证券、候选日期包络、剩余日期包络和数量，不含价格或逐日原始行情。

`--all-residual-tasks` 可将完整队列嵌入补证标准输出的 `residual_evidence_queue`，
用于下一批免费公告检索；日期包络仅是检索范围，不能被解读为所有日期均缺失或均停牌。
独立导出脚本 `scripts/v2/export_szse_evidence_queue.sh` 固定读取第三批报告（4,373日残余）。
第四批脚本已经合并补证与全量队列输出，用户无需为这两个动作分别执行命令。

## 第四批公告补证准备

累计十二条清单保留前三批八条原记录，新增四条发行人事后证据：

| 证券 | 停牌日期 | 实际复牌日期 | 新候选残余日数 | 主证据 |
| --- | --- | --- | ---: | --- |
| 000839 中信国安 | 2015-06-29 | 2015-12-28 | 121 | https://static.cninfo.com.cn/finalpage/2016-05-17/1202323307.PDF 第35页 |
| 000876 新希望 | 2015-08-17 | 2016-03-02 | 118 | https://static.cninfo.com.cn/finalpage/2017-04-28/1203412311.PDF 第67页 |
| 000538 云南白药 | 2016-07-19 | 2016-12-30 | 102 | https://static.cninfo.com.cn/finalpage/2017-04-22/1203357001.PDF 第49、50页 |
| 000917 电广传媒 | 2015-05-28 | 2015-11-13 | 111 | https://disc.static.szse.cn/disc/disk01/finalpage/2016-05-25/b8ea1c3e-3130-412b-aeb3-5fa7947aa12e.PDF 第1、3页 |

四候选合计452日，真实新增覆盖数待受限逐日匹配。
电广传媒主证据为发行人董事会程序说明，以同发行人的报告书摘要封面绑定证券代码000917：
https://static.cninfo.com.cn/finalpage/2015-11-13/1201767510.PDF 。

云南白药原文包含证券简称和代码括号，补证器逐字绑定这些身份字段；实际复牌句末逗号
必须紧接“并于同日披露了”，不能通过截短计划/条件语义获得接受。
本批还支持已审核的“自某日复牌”及明确复牌后继续推进资产收购的固定原文尾句；
停牌首日保守排除、复牌日排除、冲突保留与成员gate独立规则不变。
第三批源码快照保存于 `verifier_sources/3366018d061a69019f3e95ce01974c452b612d6f56d559b8173425b25b5e15db.py`。

累计清单：
`artifacts/v2/szse_issuer_notice_evidence/ebd1c9839ff5fc32cf4971311352bc206d32cca487e7b1f7f110a04cf51f6154.json`。

```bash
sudo bash /media/hgdl1012/84f6bd42-d506-47ff-8bf3-7b354ba37618/media/hgdl1012/program/quan/scripts/v2/supplement_szse_issuer_batch4.sh
```

标准输出中的 `newly_explained_sessions` 是相对最初月报的累计增量，包含前三批1,654日。
本批实际增量应以新 `covered_sessions` 减去3,720，并同时核对冲突数。
即使候选全部匹配也不能直接宣称成员资格通过。

本轮其他检索边界：

- 东华软件、渤海金控已找到独立财务顾问或基金年报交叉材料，以及发行人已披露复牌公告的清单。
  清单只能证明公告披露，不等同于已核实实际复牌；未将它们作为发行人实际复牌证据纳入本批。
- CSI官方调样公告再做有界检索后，五只相关沪市证券仍未获得满足“沪深300、证券调出、明确生效日”的原件。
  仅涉及上证指数的公告及普通定期调样日期不予替代，PIT成员gate继续BLOCKED_DATA。
- 原始月份证据、前批清单、报告和源码快照全部保留。

## 第四批实跑与验收

用户已回传：本批新增452日，累计覆盖4,172 / 8,093日（51.55%），残余3,921日，冲突0。
区间FULL 215、PARTIAL 121、NO_MATCH 6、CONFLICT 0。两个gate均为BLOCKED_DATA。
完整127项剩余队列已返回并核对数量守恒。所有统计来源为用户回传；未直接读取受限完整报告。

完整离线pytest 290 passed，Ruff/格式/mypy通过，独立复核无阻断发现。
回传摘要：`artifacts/v2/szse_monthly_run_receipts/7767da1faada8d021c5098fc8f7058379548185d41f1c6eb830c6adc367aca01.json`。
全量公开补证工作清单：`artifacts/v2/szse_public_evidence_worklist/98d230b634282865899047d8b90ef3dbfa837d7124ad5dd79da911e2e2cf496c.json`。
验收：`artifacts/v2/szse_issuer_supplement_qa/a8a2a13a53c45b0e7085dc4a501d4263c634692e9cd5612e55dc491d8aff94da.json`。
受限报告：`/srv/quant-v2/sealed_holdout/artifacts/v2/free_suspension/szse_issuer_supplement/d45dbbf23992bd49ce19fee0e9bc5b9268142ff2d5ab5e44d7a048e50aafa796.json`。

## 第六批补证准备

第五批实跑后，累计覆盖为 4,522 / 8,093 日，残余为 3,571 日。第六批以累计二十条人工审核的发行人证据重算，并新增以下四个事件：东方园林（2018-05-25 至 2018-08-27）、云南白药（2018-09-19 至 2018-11-23）、美的集团（2018-09-10 至 2018-10-29）和紫光股份（2017-03-07 至 2017-04-20）。候选残余日数为 60、34、15、11；实跑前不把它们记为已解释。

新主公告均绑定官方目录响应、证券代码、公告标题、原始 PDF 哈希和正文页码。目录中标记“已取消”的文件不会进入补证清单。主公告发布日期必须晚于其确认的复牌日期，因此同日“将于复牌”的实施安排不能冒充事后确认。神州信息 2017 年停牌事件与 2018 年另一停牌事件的复牌已被明确排除，不能交叉配对。

执行入口：

```bash
sudo bash /media/hgdl1012/84f6bd42-d506-47ff-8bf3-7b354ba37618/media/hgdl1012/program/quan/scripts/v2/supplement_szse_issuer_batch6.sh
```

该脚本保持原月报报告和前批报告不变，写入新的不可变 sealed 报告并附带完整残余队列。`newly_explained_sessions` 仍是相对最初月报的累计增量；实际第六批增量应按新 `covered_sessions` 减去 4,522 计算。无论该批结果如何，PIT 成员 gate 不升级。

## 全量公开目录检索与第五批实跑

已对127项剩余候选进行巨潮免费历史公告查询，证券orgId只用于定位请求，不用作历史成员证据。
已抓取170份复牌类PDF和111份年报作候选语料；部分已取消版本已明确排除资格性使用。
全量目录响应、原始PDF、提取文本和捕获时实际脚本版本均保留：`artifacts/v2/cninfo_public_discovery/6ff099f6dfe31e6e207952f372ef22db669cac9417c92f59531ceebe2fbefc1b`。

第五批新增美锦能源81日、湖北能源83日、紫光国微93日、掌趣科技93日，共350日。
已由用户固定脚本回传确认累计覆盖4,522 / 8,093日（55.88%），残余3,571日，冲突0。
区间FULL 219、PARTIAL 118、NO_MATCH 5、CONFLICT 0。两个gate继续BLOCKED_DATA。
主补证清单：`artifacts/v2/szse_issuer_notice_evidence/1cd5b99723257aa32394c6afb6d9a76257d38bfc9be692edb5fa9cbc1e3be542.json`。
湖北能源停牌起点为2014-11-18，不能把2015-01-05数据范围起点当作真实停牌日。
美锦能源采用原文第3页正确的“开市起复牌”，没有沿用第1页“开始起”的笔误。
新四条主公告逐ID核验官方目录，未标已取消；新增主公告必须晚于其实际复牌日发布的检查。

本批完整离线pytest 294 passed，Ruff/格式/mypy通过，独立复核无阻断问题。
验收：`artifacts/v2/szse_issuer_supplement_qa/e867921d370d0170c7a8a18d0d4af3c13d7a129908613ebaab0764ed894c1047`。
受限报告：`/srv/quant-v2/sealed_holdout/artifacts/v2/free_suspension/szse_issuer_supplement/87bf7d0dc24d501d4d74b683b6d68fe9b60a66e8a9d4573f49477ba3d354dc9a.json`。
统计来源为用户回传，未直接读取受限完整报告。
自动文本配对仅是线索；已明确拒绝神州信息2017停牌起点与2018另一事件复牌的错误配对。
