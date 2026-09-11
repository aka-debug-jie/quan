# quant-stack

`quant-stack` is a reproducible, Linux-first ETF research and local
paper-trading platform. Issues 001--010 provide typed data contracts, immutable
snapshots, point-in-time features, constrained long-only portfolio construction,
T+1 execution and explicit costs. Issue 009 produced a controlled-recovery
result of `NO_EVIDENCE_OF_EDGE`; it makes no profitability claim.

## Safety boundary

This version contains no broker adapter, credentials, leverage, short selling,
or real-order submission. Research execution is a local deterministic simulator;
a signal using trading day T close data cannot be filled before a later
exchange-local trading date. AKShare ingestion is explicit and not used by
tests or automatic tasks.

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

Formal Issue 009 runs remain gated by frozen configuration hashes, an immutable
data snapshot and a recorded locked-test precommit manifest.

## Paper account

The local paper account has no broker integration and cannot submit a live order.
It uses raw-price fills, Decimal fractional shares, corporate actions, SQLite WAL
storage and an append-only hash chain.

```bash
uv run quant paper initialize
uv run quant paper reconcile
uv run quant paper run-daily --allow-network
```

Daily reports are written below `artifacts/paper/`. Preview and install the
optional user-level timer without enabling it, then explicitly enable it:

```bash
bash scripts/install_paper_systemd_user.sh --preview
bash scripts/install_paper_systemd_user.sh
bash scripts/enable_paper_systemd_user.sh
```

## Layout

- `docs/`: research, data, backtest, risk, and roadmap contracts.
- `configs/`: versioned ETF universe, official-calendar snapshots, and future inputs.
- `src/quant_stack/`: typed models, data adapter, calendar, immutable ingestion, and CLI.
- `tests/`: offline fixtures and behavior tests.
- `data/`: ignored local raw, normalized, and feature datasets.
- `artifacts/`: ignored generated backtests, signals, orders, and reports.
- `scripts/`: repeatable local check entry points.
