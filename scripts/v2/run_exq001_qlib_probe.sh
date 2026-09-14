#!/usr/bin/env bash
set -euo pipefail

if [[ ${EUID} -ne 0 ]]; then
  echo "run as root: sudo bash scripts/v2/run_exq001_qlib_probe.sh" >&2
  exit 2
fi

repo_root=/media/hgdl1012/84f6bd42-d506-47ff-8bf3-7b354ba37618/media/hgdl1012/program/quan
export PYTHONPATH="$repo_root/src"
"$repo_root/.venv/bin/python" -m quant_stack_v2.exq_qlib_probe +  --development-root /srv/quant-v2/development +  --sealed-root /srv/quant-v2/sealed_holdout +  --repo-root "$repo_root" +  --registry "$repo_root/configs/v2/qualification/exq_001_candidate_scope_v1.yaml" +  --result-root /srv/quant-v2/development/exq001
