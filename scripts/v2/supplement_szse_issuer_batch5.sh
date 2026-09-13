#!/usr/bin/env bash
# Cumulative sixteen reviewed events, with the complete reduced residual queue.
set -euo pipefail
task_repo=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)
task_base=/srv/quant-v2/sealed_holdout
export PYTHONPATH="$task_repo/src"
export PYTHONDONTWRITEBYTECODE=1
exec /srv/quant-v2/results/runtime/bin/python -m quant_stack_v2.szse_issuer_supplement \
  --report "$task_base/artifacts/v2/free_suspension/szse_monthly_verification/b31fc67f7707cb728f1606b45ce909e0d1907991e62075be050b95a3ad186873.json" \
  --manifest "$task_repo/artifacts/v2/szse_issuer_notice_evidence/1cd5b99723257aa32394c6afb6d9a76257d38bfc9be692edb5fa9cbc1e3be542.json" \
  --all-residual-tasks \
  --output-root "$task_base/artifacts/v2/free_suspension/szse_issuer_supplement"
