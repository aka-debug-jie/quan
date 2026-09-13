#!/usr/bin/env bash
# Fixed reviewed evidence; offline; preserves original report and sealed permissions.
set -euo pipefail
task_repo=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)
task_base=/srv/quant-v2/sealed_holdout
export PYTHONPATH="$task_repo/src"
export PYTHONDONTWRITEBYTECODE=1
exec /srv/quant-v2/results/runtime/bin/python -m quant_stack_v2.szse_issuer_supplement \
  --report "$task_base/artifacts/v2/free_suspension/szse_monthly_verification/b31fc67f7707cb728f1606b45ce909e0d1907991e62075be050b95a3ad186873.json" \
  --manifest "$task_repo/artifacts/v2/szse_issuer_notice_evidence/bfa6639ef00fffda27feb41ed9d366492bfdc6deffc976f0541179dc01c1ed88.json" \
  --output-root "$task_base/artifacts/v2/free_suspension/szse_issuer_supplement"
