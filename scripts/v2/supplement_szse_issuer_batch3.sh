#!/usr/bin/env bash
# Cumulative eight-claim offline audit; original reports and permissions remain intact.
set -euo pipefail
task_repo=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)
task_base=/srv/quant-v2/sealed_holdout
export PYTHONPATH="$task_repo/src"
export PYTHONDONTWRITEBYTECODE=1
exec /srv/quant-v2/results/runtime/bin/python -m quant_stack_v2.szse_issuer_supplement \
  --report "$task_base/artifacts/v2/free_suspension/szse_monthly_verification/b31fc67f7707cb728f1606b45ce909e0d1907991e62075be050b95a3ad186873.json" \
  --manifest "$task_repo/artifacts/v2/szse_issuer_notice_evidence/efb3ff91a785dc9e81ad8f6e2a0f1365c2290c6ec8adcf3b1709f37e6a3bcfa6.json" \
  --output-root "$task_base/artifacts/v2/free_suspension/szse_issuer_supplement"
