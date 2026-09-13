#!/usr/bin/env bash
# Fixed-input, offline audit. User runs as sudo/quant-eval; no permission changes.
set -euo pipefail
task_repo=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)
task_base=/srv/quant-v2/sealed_holdout
export PYTHONPATH="$task_repo/src"
export PYTHONDONTWRITEBYTECODE=1
exec /srv/quant-v2/results/runtime/bin/python -m quant_stack_v2.szse_verification \
  --index "$task_repo/artifacts/v2/szse_monthly_evidence/2140ec9a8ca8e17a542a7d8337ed3d672f655c86acf3446d82d8bc691b662ac1.json" \
  --plan "$task_base/artifacts/v2/free_suspension/official_suspension_plans/a6ee1184dab840f669a53d4bef4fb2fe760087125f419af2f9260ce36385d7a7.json" \
  --audit "$task_base/artifacts/v2/qlib_daily_audit/csi300/a32fd25153ab969cca5f6dc087ec724950fb2ab1514a55b02c2ec0a257d47d3c.json" \
  --expected-intervals 342 --expected-sessions 8093 \
  --output-root "$task_base/artifacts/v2/free_suspension/szse_monthly_verification"
