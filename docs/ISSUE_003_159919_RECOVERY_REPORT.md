# Issue 003 — 159919 secondary-source recovery report

## Decision

**BLOCKED.** The recovery architecture is implemented and its offline tests pass,
but the captured official SZSE endpoint cannot supply the required 2015-onward
raw history. It is not eligible for canonical selection, and no qfq data has
been generated.

## Subsequent recovery evidence

- SZSE parameter probes (base, `page=2&pageSize=5000`, and the full 2015--2026
  date window) each returned the same 201 sessions. The short result is a source
  limitation, not adapter pagination.
- Independent Sina raw manifest
  `08a5902f92d0f2c78cc900742bba88886057339dc440c5c0c580f5cffd983f6d`
  contains 2,840 sessions from 2015-01-05 through 2026-09-09. Its sole absent
  session, 2019-01-11, is an evidence-backed fund-share conversion suspension.
- The first-party 嘉实 source body is archived under SHA-256
  `d58b052dc8a29c43b75b59fc45ac215df4182ceb69743ddeb9eca1da50c7ba97`.
  It also records the 1.110680861 share conversion in the still-incomplete ledger.
- Sina and SZSE reconcile across all 201 overlapping sessions: OHLC match exactly;
  Sina shares are converted to SZSE lots by 0.01 with at most 0.5-lot source
  reporting quantization. Raw canonical manifest:
  `5ec4e243b363d52d5a379fea1fef3c4a1258b51ee00fa4717cc7bcceecc40de4`.

This establishes raw coverage only. The action ledger remains incomplete, so no
canonical qfq artifact is published and the A--J gate remains blocked.

## Preserved primary-provider state

AKShare `fund_etf_hist_em` / Eastmoney remains the primary provider. Its existing
`159919` TLS-disconnect failure evidence and its absence of normalized `159919`
data were neither changed nor deleted. A secondary source is an independent
provider-native series; it is never concatenated with, or substituted into, the
AKShare series.

## SZSE official secondary receipt

The explicit network command was:

```bash
uv run quant data ingest-szse-raw \
  --universe configs/assets/etf_universe_v2.yaml \
  --start 2015-01-01 --as-of 2026-09-09 --allow-network
```

It exited non-zero as intended because coverage was incomplete, after publishing
only immutable provider-native artifacts:

| Field | Captured value |
| --- | --- |
| Provider | `szse_official` |
| Endpoint | `https://www.szse.cn/api/market/ssjjhq/getHistoryData?cycleType=32&marketId=1&code=159919` |
| Retrieval timestamp | `2026-09-09T17:59:07.916672Z` |
| Request | `cycleType=32`, `marketId=1`, `code=159919` |
| HTTP receipt | `200`, `content-type: application/json;charset=UTF-8`, `content-length: 23222`, `server: nginx` |
| Parser / normalization | `1.0.0` / `1.0.0` |
| Provider manifest | `adcb44a52af32e063dea9da605fe4beb98374864e321972230fb7526eda7988b` |
| Raw JSON SHA-256 | `f364f1c385661d9c6ede8aba1894430bd8f95eb349d120ac9eea9f448fea735f` |
| Normalized provider Parquet SHA-256 | `3ec090698effd1df896049e66cac2dd153c23efebbfe00da8d3b893283c70677` |
| Native bars | 201; 2025-11-14 through 2026-09-09 |
| Raw OHLC invariant | passed for all 201 parsed bars |
| Expected sessions missing (2015-01-01 to 2026-09-09) | 2,640; first 2015-01-05, last 2025-11-13 |

The raw JSON, native Parquet, and JSON manifest reside under the Git-ignored
`data/` tree. Their paths are recorded in the provider manifest; no data artifact
is committed.

## Corporate-action ledger and qfq boundary

`configs/corporate_actions/159919_v1.yaml` is the versioned ledger record. It is
explicitly `incomplete` and contains zero asserted events. This is deliberate:
no complete, primary-source-backed list of distributions, share consolidations,
or other price-continuity events was established during this recovery.

The code captures each future primary-source body by content hash under
`data/raw/corporate_action_evidence/<sha256>/evidence.bin`; a ledger marked
`complete` must name those immutable records. The deterministic local qfq
algorithm accepts only one validated raw provider series plus such a complete
ledger. It cannot run for this ledger, so it cannot fabricate qfq prices.

## Cross-provider reconciliation

The reconciliation implementation compares full raw OHLCV records only on
overlapping dates and never fills dates or joins series. This run has no
independently captured, comparable 159919 raw provider series: AKShare has no
successful `159919` capture and Tushare is unavailable (`tushare_module=False`,
`tushare_token_configured=False`). Its reconciliation result is therefore
`blocked`, with zero overlap and zero comparisons—not a pass by absence of
disagreement.

## A–J gate evaluation

| Gate | Result | Reason |
| --- | --- | --- |
| A raw coverage complete | fail | 2,640 expected sessions lack SZSE raw bars; AKShare still has none. |
| B qfq coverage complete | fail | No qfq is published; incomplete ledger blocks derivation. |
| C all gaps evidenced | fail | The 2,640 raw absences have no per-date official status evidence. |
| D no unexplained gap | fail | Same 2,640 expected-session gaps. |
| E OHLC invariants | pass, limited | All 201 captured SZSE bars validate; this does not establish full history. |
| F complete corporate-action ledger | fail | Ledger v1 is explicitly incomplete, with no asserted evidence-backed events. |
| G qfq reproducible from raw + ledger | fail | Prerequisite ledger is incomplete. |
| H cross-provider verification | fail | No independently captured overlapping raw series. |
| I deterministic canonical rerun | not applicable | Code test passes for a complete synthetic fixture; no actual canonical dataset is eligible. |
| J all test classes and real-data validation | fail | Offline tests pass, but A–I real-data gates do not. |

No Issue 004–012 work may start from this branch.
