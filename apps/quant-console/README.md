# Quant Console V1

中文、本地、只读的 Quant Stack 研究控制台。应用只消费已发布的结构化结果，
不会初始化账户、重建账本、抓取行情、运行实验、控制 timer 或提交订单。

## 独立环境

后端要求 Python 3.11，并使用本目录后端自己的 `uv.lock`：

```bash
uv sync --project apps/quant-console/backend --locked --all-groups
```

前端要求 Node 20，并使用 `package-lock.json`：

```bash
cd apps/quant-console/frontend
npm ci --no-audit --no-fund
npm run build
```

把 `dist/` 复制到 Console 独立 runtime 的 `static/`。不要把 runtime、来源配置、
真实截图或研究数据提交到 Git。

## 配置和启动

复制 `config/sources.example.toml` 到 Console runtime，填入四个已经批准的本机来源。
source root 只能在启动时配置，浏览器和 API 不接受路径。

```bash
bash apps/quant-console/scripts/start-local.sh \
  /absolute/console/runtime/sources.toml \
  /absolute/console/runtime \
  /absolute/console/python-env \
  /absolute/console/runtime/static
```

打开 `http://127.0.0.1:8765`。停止时在启动终端按 `Ctrl+C`。脚本不会安装或启用
systemd unit。远程查看使用 SSH 本地转发：

```bash
ssh -L 8765:127.0.0.1:8765 user@host
```

不要把服务改为 `0.0.0.0`。卸载只删除 Console 自己的工作树、独立环境、npm 缓存、
浏览器和 runtime；不要删除来源目录。删除前应先停止 Console 并核对目标路径。

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

CI 与演示模式使用合成数据，并始终显示“演示数据，不是研究结果”。真实模式缺少来源
时直接报错，不会静默切换为演示。
