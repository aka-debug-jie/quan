#!/usr/bin/env bash
# Fixed source, reduced evidence-request metadata only; no permission changes.
set -euo pipefail
task_repo=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)
task_base=/srv/quant-v2/sealed_holdout
export PYTHONPATH="$task_repo/src"
export PYTHONDONTWRITEBYTECODE=1
exec /srv/quant-v2/results/runtime/bin/python -m quant_stack_v2.szse_evidence_queue \
  --report "$task_base/artifacts/v2/free_suspension/szse_issuer_supplement/d924987b0764e74a0bc143b3bc9f1c9e70a5c62befbe3c9ece3a94195149c605.json" \
  --expected-residuals 4373 \
  --output-root "$task_base/artifacts/v2/free_suspension/szse_evidence_queue"
