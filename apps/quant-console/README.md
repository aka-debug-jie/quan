# Quant Console V1.5

中文、本地、只读的 Quant Stack 研究控制台。V1.5 使用强类型 Pydantic/OpenAPI
契约、生成的 TypeScript 客户端、TanStack Query、AG Grid Community、Radix UI
primitives 和 ECharts。应用只消费已发布结构化结果，不初始化账户、不重建研究
账本、不抓取行情、不运行实验、不控制 timer，也不存在下单入口。

## 环境与构建

后端使用 Python 3.11 和本目录独立 `uv.lock`：

```bash
uv sync --project apps/quant-console/backend --locked --all-groups
```

前端使用 Node 20.19.5 和独立 `package-lock.json`：

```bash
cd apps/quant-console/frontend
npm ci --ignore-scripts --no-audit --no-fund
npm run lint
npm run typecheck
npm run test
npm run build
```

生成接口契约不得读取真实研究数据：

```bash
uv run --project apps/quant-console/backend quant-console openapi \
  --output apps/quant-console/frontend/openapi.json
cd apps/quant-console/frontend
npm run generate:api
cd ../../..
bash apps/quant-console/scripts/check-contract.sh
```

把前端 `dist/` 复制到 Console 独立 runtime 的 `static/`。不要把 runtime、真实
source 配置、浏览器 trace、截图或研究数据提交到 Git。

## 真实来源初始化

复制 `config/sources.example.toml` 到 Console 自己的 runtime。来源根只可在启动时
配置；浏览器和 HTTP API 不接受本机路径。授权来源为 Historical V3、Quant
Upgrade V1、V2 closure/acceptance 和 prospective RC-02 已发布 JSON。应用不读取
prospective 账户 SQLite。

```bash
/path/to/python-env/bin/quant-console observe-system \
  --output /path/to/console-runtime/system-observation.json
/path/to/python-env/bin/quant-console index \
  --config /path/to/console-runtime/sources.toml \
  --runtime /path/to/console-runtime
```

`index` 在 staging 中校验源哈希，生成 schema v2 Experiment Ledger、详情和时序
文件，验证后原子切换 `current.json`；失败时保留上一可用快照。

## 启动和停止

```bash
bash apps/quant-console/scripts/start-local.sh \
  /path/to/console-runtime/sources.toml \
  /path/to/console-runtime \
  /path/to/python-env \
  /path/to/console-runtime/static \
  8766
```

打开 `http://127.0.0.1:8766`。停止时在启动终端按 `Ctrl+C`。脚本不会安装或启用
systemd 服务。远程查看只能使用 SSH 本地转发：

```bash
ssh -L 8766:127.0.0.1:8766 user@host
```

不得改成 `0.0.0.0`。应用发现新快照时会提示切换，不会把旧请求结果静默覆盖到
当前页面。

## 更新、回退和导出

更新代码后重新执行 locked install、契约检查、前端构建和 `index`。V1.5 runtime
与 V1 runtime 相互独立；回退时停止 V1.5，按旧 V1 README 启动，不删除研究来源。

实验中心仅导出服务端白名单内的聚合字段，明确区分选中项和全部过滤结果并绑定
snapshot。CSV 启用公式注入防护。禁止导出原始行情、持仓、订单、账户库、服务器
配置、sealed/CSI500 内容或本机绝对路径。

## 验证

```bash
cd apps/quant-console/backend
uv run ruff check .
uv run ruff format --check .
uv run mypy src tests
uv run pytest --cov=quant_console

cd ../frontend
npm run lint
npm run typecheck
npm run test
npm run build
npm run e2e
```

CI 只使用带明显标识的合成数据。真实模式缺来源时明确失败，绝不静默切换到演示
模式。演示模式所有页面持续显示“演示数据，不是研究结果”。
