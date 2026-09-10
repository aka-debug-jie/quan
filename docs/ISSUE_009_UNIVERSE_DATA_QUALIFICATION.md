# Issue 009-D0 Frozen Universe Data Qualification

Status: `PASS`
Substage: `009-D0`
Locked test: not run

This is a pre-locked-test data qualification result. It does not report a
strategy result or change the frozen universe, benchmark, strategy, cost model,
timing rule, parameter grid, or split.

## Final qualification

Artifact: `artifacts/data_qualification/4a554e464cef4f836187484cd9d4c364d57ed5e6dda698c926d5e0067ec46940/qualification.json`

| Symbol | Raw | Inventory | Ledger | PIT | Causal | Reconciliation | Reproducible | Result |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| `159919` | PASS | PASS | PASS | PASS | PASS | PASS | PASS | QUALIFIED |
| `510300` | PASS | PASS | PASS | PASS | PASS | PASS | PASS | QUALIFIED |
| `510500` | PASS | PASS | PASS | PASS | PASS | PASS | PASS | QUALIFIED |

The source registry SHA-256 is
`cd420fd578e50a1e3b8293856a8c4c9cd7c80942994879c4cfe028e69887ad2c`.
It selects one complete SSE official raw series for each SSE asset, retains
AKShare/Eastmoney as the full-history cross-check, and uses Sina only as a
third-provider adjudicator. No provider rows are spliced.

## Event inventories

| Symbol | Rows | Dividends | Splits/conversions | Unexplained | Inventory artifact |
| --- | ---: | ---: | ---: | ---: | --- |
| `510300` | 12 | 12 | 0 | 0 | `2e8f49ba1201bbe4afaf603a8aa94a56669bbf6f4bf508142353c31e5f06bf01` |
| `510500` | 6 | 4 | 2 | 0 | `854a08fae470574e1493559fc3339288f54f7e828ea0523d00a1ef8aee4db11d` |
| `159919` | 6 | 5 | 1 | 0 | `a15cc549ed928d6bceb950a63670d3844720b4294771723a7f79263ae45edcca` |

The former `510300` candidate is now `VERIFIED_DIVIDEND`. The SSE original
notice was published on 2015-01-14 and records fund code `510300`, CNY 0.35 per
10 units, record date 2015-01-19, ex-date 2015-01-20, and payment date
2015-01-23. Its archived body SHA-256 is
`1edb820f5efe41a0f28f7bd05dfdaf454e0dde97894a4101f6b9570c1b2bf3db`.

The SSE announcement-directory responses cover 2015-01-01 through 2026-09-10.
Both response and receipt hashes are bound in the source registry. The complete
directories reconcile all ledger rows in both directions; neither SSE asset
has an unexplained provider adjustment candidate or official event.

## Raw reconciliation

| Symbol | Sessions | AKShare differences | Sina-confirmed SSE values | Source rejected | Unexplained | Report |
| --- | ---: | ---: | ---: | ---: | ---: | --- |
| `510300` | 2,841 | 5 | 5 | 0 | 0 | `49659bc62c4cf03dccfc3019c8b78c5b5c9e3e84421563ec5c203b19f6defd74` |
| `510500` | 2,839 | 5 | 5 | 0 | 0 | `14634c11db3afc9832024034f2cc3d2f897cf6f2d9f6e8a169daf05c5efaec92` |

The five differences for each asset occur on 2020-08-21 and 2020-08-24 through
2020-08-27. Each SSE OHLC record is independently matched by Sina. Maximum
absolute differences are `0.001`; corporate-action-boundary mismatches are
zero. The earlier isolated Sina discrepancies match AKShare and SSE and are not
present in the canonical-source reconciliation.

## Causal outputs and reproduction

| Symbol | Ledger SHA-256 | Causal output SHA-256 | Reproduction report |
| --- | --- | --- | --- |
| `510300` | `d4ae033d73c0ab352930d2e70f64039e6176c330e2f159be24920f889328f53f` | `c108505b68156c28b1b9190dbf0f4d3c7e9d3468d960fee77c20c66729f9a00d` | `a5e75fd94d36894c6d8717de2b586bb5f9891582c22aba18ee12dbbaf42ddd0b` |
| `510500` | `3930b6e171ff790e71c68b54f0a0eb35877a0a432d0bd152e05d7aacedc486a1` | `3e1a90f772b7614c1d5927a2710761d677baf8c63e6d36e8eeb3135e0903f1cc` | `ec4e7bb9f51c54ac89fd634ef9e46ea1450da018a759723a971a8857bf1012f3` |
| `159919` | `448c11403a9af0cfe49333c5b067b366d72f0e336d9597cf3c3a6b3d19bd8cf6` | `9b096bc92625404ea6c70a44e00218bf41de59c3c69a762cd7d78a1709cd6d26` | `83a44e0c1ccbee1a6c7c41e13fab6ad2f3f533d8c66cc3aa1448ba6e824c0bef` |

All three reports rebuilt the selected raw snapshot and complete ledger in an
isolated temporary root with algorithm version `1.0.0` and code commit
`6081641`. Observed manifest and output hashes exactly equal the retained
canonical artifacts. A regression test also verifies that a future action does
not change an earlier adjusted input, feature, or signal, and raw OHLC remains
unchanged.

## Validation and boundary

Ruff, format check, strict mypy, and `117 passed` with coverage. The locked test
was not run. D0 now permits creation of a new `LOCKED_TEST_PRECOMMIT`; none was
created in this change, and no Issue 010-012 work was started.
