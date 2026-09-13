#!/usr/bin/env bash
# Offline, fixed-input verification; run as quant-eval after provisioning output.
set -euo pipefail
task_repo=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)
task_base=/srv/quant-v2/sealed_holdout
export PYTHONPATH="$task_repo/src"
exec /srv/quant-v2/results/runtime/bin/python -m quant_stack_v2.sse_verification \
  --index "$task_base/data/external/sse_suspension_batches/e635f975f8836407d0814de60444c744c0cff7fcd0ab86faa8376484760e8e91/index.json" \
  --plan "$task_base/artifacts/v2/free_suspension/official_suspension_plans/a6ee1184dab840f669a53d4bef4fb2fe760087125f419af2f9260ce36385d7a7.json" \
  --audit "$task_base/artifacts/v2/qlib_daily_audit/csi300/a32fd25153ab969cca5f6dc087ec724950fb2ab1514a55b02c2ec0a257d47d3c.json" \
  --data-root "$task_base/data/external" \
  --output-root "$task_base/artifacts/v2/free_suspension/sse_verification"
