#!/usr/bin/env bash
set -euo pipefail
repo_root=/media/hgdl1012/84f6bd42-d506-47ff-8bf3-7b354ba37618/media/hgdl1012/program/quan
test -z "$(git -C "$repo_root" status --porcelain)"
export PYTHONPATH="$repo_root/src"
"$repo_root/.venv/bin/python" -m quant_stack_v2.exq_szse_replay --queue-root /srv/quant-v2/development/exq001/official_evidence_queue --queue-sha256 b1e9194b9be4cb9b796edc0926b4c85e532ffef25273ddaa3b4677fcb0a206c5 --monthly-index "$repo_root/artifacts/v2/szse_monthly_evidence/2140ec9a8ca8e17a542a7d8337ed3d672f655c86acf3446d82d8bc691b662ac1.json" --result-root /srv/quant-v2/development/exq001
