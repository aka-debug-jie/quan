#!/usr/bin/env bash
# Cumulative six-claim audit against the original monthly report; no permission changes.
set -euo pipefail
task_repo=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)
task_base=/srv/quant-v2/sealed_holdout
export PYTHONPATH="$task_repo/src"
export PYTHONDONTWRITEBYTECODE=1
exec /srv/quant-v2/results/runtime/bin/python -m quant_stack_v2.szse_issuer_supplement \
  --report "$task_base/artifacts/v2/free_suspension/szse_monthly_verification/b31fc67f7707cb728f1606b45ce909e0d1907991e62075be050b95a3ad186873.json" \
  --manifest "$task_repo/artifacts/v2/szse_issuer_notice_evidence/f92a067587978322c286578299105d982d3cf8fd61aa27da725bf61f58f79cfa.json" \
  --output-root "$task_base/artifacts/v2/free_suspension/szse_issuer_supplement"
