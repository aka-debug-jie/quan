# quant-stack

`quant-stack` is a reproducible, Linux-first quantitative research skeleton.
M0 plus Issues 001–003 define typed data contracts, an AKShare ETF adapter,
immutable local snapshots, source-attributed local calendars, offline fixtures,
and command-line entry points. It does not implement a profitable strategy and
does not claim that backtest results predict future returns.

## Safety boundary

This version contains no strategy, backtest, broker adapter, credentials,
leverage, short selling, or real-order submission. AKShare ingestion is an
explicit, operator-invoked data operation; it is not used by tests or automatic
tasks. A signal using trading day T close data cannot be filled before a later
exchange-local trading date.

## Install

Install `uv`, then from this directory run:

```bash
uv sync --locked
```

The project requires Python 3.11. Dependencies are resolved in `uv.lock`.

## Checks

```bash
uv run ruff check .
uv run ruff format --check .
uv run mypy src
uv run pytest --cov=quant_stack
```

Tests use only the synthetic CSV under `tests/fixtures`; they never access the
network.

## CLI

```bash
uv run quant data validate tests/fixtures/synthetic_etf_daily.csv
uv run quant data snapshot tests/fixtures/synthetic_etf_daily.csv /tmp/quant-raw
uv run quant calendar validate --exchange SSE --year 2024
uv run quant data coverage \
  --universe configs/assets/etf_universe_v2.yaml \
  --start 2015-01-01 --as-of YYYY-MM-DD
```

To deliberately fetch market data, supply an already-confirmed trading date and
the required network switch:

```bash
uv run quant calendar capture-sources \
  --start-year 2015 --end-year 2026 --allow-network

uv run quant data capture-non-trading-evidence \
  --universe configs/assets/etf_universe_v2.yaml --allow-network

uv run quant data ingest-etf \
  --universe configs/assets/etf_universe_v2.yaml \
  --start 2015-01-01 --as-of YYYY-MM-DD \
  --allow-network
```

The calendar and non-trading-evidence commands store hash-checked official
source bodies before data ingestion. ETF ingestion stores raw provider exports,
normalized raw/qfq Parquet files, and immutable manifests under `data/`. It
exits non-zero for any unresolved expected trading-session gap. A documented
non-trading session never creates an OHLC bar or a synthetic price. Verify a
normalized file locally with:

```bash
uv run quant data verify data/normalized/.../snapshot.parquet
```

Backtest, signal, and reconciliation commands remain explicit M0 placeholders.

## Layout

- `docs/`: research, data, backtest, risk, and roadmap contracts.
- `configs/`: versioned ETF universe, official-calendar snapshots, and future inputs.
- `src/quant_stack/`: typed models, data adapter, calendar, immutable ingestion, and CLI.
- `tests/`: offline fixtures and behavior tests.
- `data/`: ignored local raw, normalized, and feature datasets.
- `artifacts/`: ignored generated backtests, signals, orders, and reports.
- `scripts/`: repeatable local check entry points.
