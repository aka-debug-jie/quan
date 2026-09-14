# EXQ-001 independent raw-provider capture

Status: CAPTURE_COMPLETE; receipt identity:
47c730bd611b100fadcd377e8133c8cf81734493ed297fe31d9a6da913eca9ed.

The capture was limited to the 278 exact frozen residual keys that intersect
the AF-003 candidate dependency scope. Every request used the unadjusted
AKShare/Eastmoney daily-history route and was content-addressed in the sealed
store with its request metadata.

| Result | Count |
| --- | ---: |
| Exact requests | 278 |
| Archived manifests | 278 |
| Empty daily responses | 278 |
| Provider failures | 0 |

An empty third-party daily response is independent-provider evidence of no
returned daily bar. It is not an exchange-confirmed halt, a contemporaneously
available trading-status flag, a corporate-action ledger, or an executable raw
price. It therefore does not justify removing a signal at T or upgrading
EXQ-001's BLOCKED_DATA status.

FORMAL_PIT_STATUS=BLOCKED_DATA,
FORMAL_RESEARCH_STATUS=BLOCKED_DATA, and CSI500=NOT_STARTED are unchanged.
