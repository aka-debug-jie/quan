# Quant Console V1.5 design

Status: implemented local read-only application design.

## Identity and read model

V1.5 rebuilds approved Historical V3, Quant Upgrade V1 and prospective published JSON
into an independent schema-v2 read model. `snapshot_id` hashes canonical component files
and excludes publication time. A no-change reload therefore retains the same identity.
`published_at` remains separate. New snapshots are staged, hash-verified and atomically
published; a failed rebuild preserves the previous pointer.

The rebuild produces a Parquet Experiment Ledger, compact experiment summaries, structured
details, evidence, health and per-series files. The Web process reads only these published
files. It verifies the manifest once per immutable snapshot and keeps a bounded in-memory
cache, avoiding V1's repeated parsing of a 5 MB monolith.

## Contracts and snapshot consistency

FastAPI endpoints use strict Pydantic response models. OpenAPI is generated without source
data, then `openapi-typescript` and `openapi-fetch` produce the checked-in frontend contract.
All immutable resources live below `/api/v1/snapshots/{snapshot_id}`. Query keys include
that identity; late responses for an old version cannot replace a selected version.

Engineering state, absolute evaluability, benchmark comparability, economic outcome, input
phase, source freshness and integrity remain independent. `NOT_EVALUABLE` is never rendered
as zero or `NO_EDGE`. Metric objects carry unit, basis, scenario, data level and evidence.

## User interface

TanStack Query owns request cancellation and cache lifetimes. AG Grid Community uses the
client-side row model because the real registry contains 61 aggregate rows; a synthetic
10,000-row contract test protects the chosen limit. Search, filters, sorting, selection,
comparison and snapshot identity are URL-driven. Column layout is versioned local UI state.

Radix primitives provide dialog, tabs and tooltip behavior. ECharts remains the only chart
engine and is route-lazy. NAV is source series; drawdown is a clearly labelled
`RUNNING_PEAK_DRAWDOWN_V1` display derivation. Full-period metrics never change when the
chart is zoomed.

## Security boundary

The server binds to loopback, validates Host and Origin, sets CSP/frame/referrer headers and
returns typed errors without paths or stacks. Browser routes cannot pass file paths, SQL or
commands. Safe exports are server-whitelisted and snapshot-bound. Systemd observation stays
a fixed-target CLI action outside HTTP.

No Web module imports the market provider, runner, broker, SQLite, systemctl or subprocess.
Raw market data, positions, accounts, sealed content and CSI500 are not indexed or exported.
Explicit reload only rereads startup-configured structured roots and writes Console runtime.

