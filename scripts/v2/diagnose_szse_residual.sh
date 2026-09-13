#!/usr/bin/env bash
# User-run offline diagnostics; preserves source reports and access permissions.
set -euo pipefail
task_repo=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)
task_base=/srv/quant-v2/sealed_holdout
export PYTHONPATH="$task_repo/src"
export PYTHONDONTWRITEBYTECODE=1
exec /srv/quant-v2/results/runtime/bin/python -m quant_stack_v2.szse_residual \
  --report "$task_base/artifacts/v2/free_suspension/szse_monthly_verification/b31fc67f7707cb728f1606b45ce909e0d1907991e62075be050b95a3ad186873.json" \
  --index "$task_repo/artifacts/v2/szse_monthly_evidence/2140ec9a8ca8e17a542a7d8337ed3d672f655c86acf3446d82d8bc691b662ac1.json" \
  --expected-residuals 6027 \
  --output-root "$task_base/artifacts/v2/free_suspension/szse_residual_diagnostics"
