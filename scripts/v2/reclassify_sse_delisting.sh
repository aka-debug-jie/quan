#!/usr/bin/env bash
set -euo pipefail
task_repo=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)
export PYTHONPATH="$task_repo/src"
exec /srv/quant-v2/results/runtime/bin/python -m quant_stack_v2.delisting_recovery \
  --root /srv/quant-v2/sealed_holdout/artifacts/v2/free_suspension/delisting_verification \
  --previous /srv/quant-v2/sealed_holdout/artifacts/v2/free_suspension/sse_verification/c73fef79bde394f0fcbd1b667237e3b76ae77c17c26ebddfc1da7e9941337e97.json \
  --manifest "$task_repo/artifacts/v2/delisting_evidence/manifests/45050aa72929b343813030341b444889b9eae7ca324882ec48d96b99b18f0216.json"
