#!/usr/bin/env bash
set -euo pipefail

if [[ ${EUID} -ne 0 ]]; then
  echo "run as root: sudo bash scripts/v2/run_exq001_raw_capture.sh" >&2
  exit 2
fi

repo_root=/media/hgdl1012/84f6bd42-d506-47ff-8bf3-7b354ba37618/media/hgdl1012/program/quan
development_root=/srv/quant-v2/development
sealed_root=/srv/quant-v2/sealed_holdout
result_root=/srv/quant-v2/development/exq001
registry="$repo_root/configs/v2/qualification/exq_001_candidate_scope_v1.yaml"
report="$repo_root/docs/v2/EXQ_001_RAW_CAPTURE_RESULT.md"
python_bin="$repo_root/.venv/bin/python"

test -z "$(git -C "$repo_root" status --porcelain)"
test -x "$python_bin"
test -d "$development_root/dev001"
test -d "$sealed_root/artifacts/v2/free_evidence_funnel"

export PYTHONPATH="$repo_root/src"
"$python_bin" -m quant_stack_v2.exq_capture \
  --development-root "$development_root" \
  --sealed-root "$sealed_root" \
  --repo-root "$repo_root" \
  --registry "$registry" \
  --result-root "$result_root" \
  --report "$report" \
  --allow-network \
  --workers 4

if getent group quant-v2 >/dev/null; then
  chgrp -R quant-v2 "$result_root"
fi
chmod -R u=rwX,g=rX,o= "$result_root"
if [[ -n ${SUDO_UID:-} && -n ${SUDO_GID:-} ]]; then
  chown "$SUDO_UID:$SUDO_GID" "$report"
fi
