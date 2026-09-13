#!/usr/bin/env bash
set -euo pipefail

if [[ ${EUID} -ne 0 ]]; then
  echo "run as root: sudo bash scripts/v2/run_dev001.sh" >&2
  exit 2
fi

repo_root=/media/hgdl1012/84f6bd42-d506-47ff-8bf3-7b354ba37618/media/hgdl1012/program/quan
sealed_root=/srv/quant-v2/sealed_holdout
development_root=/srv/quant-v2/development/dev001
python_bin="$repo_root/.venv/bin/python"
report="$repo_root/docs/v2/DEV_001_RESULT.md"

git -C "$repo_root" merge-base --is-ancestor 98d6f8a026565d423278f48ee41b8f5580da4be3 HEAD
test -x "$python_bin"
test -d "$sealed_root"
install -d -m 0750 "$development_root"

export PYTHONPATH="$repo_root/src"
export MPLCONFIGDIR=/tmp/quant-dev001-matplotlib
"$python_bin" -m quant_stack_v2.dev001 \
  --sealed-root "$sealed_root" \
  --development-root "$development_root" \
  --repo-root "$repo_root" \
  --report "$report"

if getent group quant-v2 >/dev/null; then
  chgrp -R quant-v2 "$development_root"
fi
chmod -R u=rwX,g=rX,o= "$development_root"
if [[ -n ${SUDO_UID:-} && -n ${SUDO_GID:-} ]]; then
  chown "$SUDO_UID:$SUDO_GID" "$report"
fi
