#!/usr/bin/env bash
set -euo pipefail
repo_root=/media/hgdl1012/84f6bd42-d506-47ff-8bf3-7b354ba37618/media/hgdl1012/program/quan
test -z "$(git -C "$repo_root" status --porcelain)"
export PYTHONPATH="$repo_root/src"
"$repo_root/.venv/bin/python" -m quant_stack_v2.exq_cninfo_batch --replay-root /srv/quant-v2/development/exq001/szse_monthly_replay --replay-sha256 e60a76448db4b23ae8872b716dd0f422cd2ddf878f99c078c6f1dc5814bf0919 --sealed-root /srv/quant-v2/sealed_holdout --result-root /srv/quant-v2/development/exq001 --allow-network
