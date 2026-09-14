#!/usr/bin/env bash
set -euo pipefail

if [[ ${EUID} -ne 0 ]]; then
  echo "run as root: sudo bash scripts/v2/run_af001.sh" >&2
  exit 2
fi

repo_root=/media/hgdl1012/84f6bd42-d506-47ff-8bf3-7b354ba37618/media/hgdl1012/program/quan
development_root=/srv/quant-v2/development/dev001
result_root=/srv/quant-v2/development/af001
registry="$repo_root/configs/v2/alphas/af_001_alpha_registry_v1.yaml"
report="$repo_root/docs/v2/AF_001_RESULT.md"
python_bin="$repo_root/.venv/bin/python"

git -C "$repo_root" diff --quiet
test -x "$python_bin"
test -f "$registry"
test -d "$development_root"
install -d -m 0750 "$result_root"

export PYTHONPATH="$repo_root/src"
"$python_bin" -m quant_stack_v2.af001 \
  --development-root "$development_root" \
  --repo-root "$repo_root" \
  --registry "$registry" \
  --result-root "$result_root" \
  --report "$report"

if getent group quant-v2 >/dev/null; then
  chgrp -R quant-v2 "$result_root"
fi
chmod -R u=rwX,g=rX,o= "$result_root"
if [[ -n ${SUDO_UID:-} && -n ${SUDO_GID:-} ]]; then
  chown "$SUDO_UID:$SUDO_GID" "$report"
fi
