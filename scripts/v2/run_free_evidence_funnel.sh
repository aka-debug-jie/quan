#!/usr/bin/env bash
set -euo pipefail
if [[ ${EUID} -ne 0 ]]; then echo "run as root" >&2; exit 2; fi
repo=/media/hgdl1012/84f6bd42-d506-47ff-8bf3-7b354ba37618/media/hgdl1012/program/quan
sealed=/srv/quant-v2/sealed_holdout
audit="$sealed/artifacts/v2/qlib_daily_audit/csi300/a32fd25153ab969cca5f6dc087ec724950fb2ab1514a55b02c2ec0a257d47d3c.json"
szse="$sealed/artifacts/v2/free_suspension/szse_history_verification/758c6cfed64d640ccdd1ba1c4b34269052b8a0ce952ac33e12d36a6148ad3164.json"
sse_dir="$sealed/artifacts/v2/free_suspension/sse_verification"
mapfile -t reports < <(find "$sse_dir" -maxdepth 1 -type f -name '*.json' | sort)
[[ ${#reports[@]} -eq 1 ]] || { echo "expected exactly one frozen SSE report" >&2; exit 2; }
export PYTHONPATH="$repo/src"
exec "$repo/.venv/bin/python" -m quant_stack_v2.free_evidence_funnel --audit "$audit" --sse "${reports[0]}" --szse "$szse" --calendar "$sealed/artifacts/v2/qlib_import/eccf69b778f7147502add9f975115c8f057a04b20b073122d9cad12f31889a7e/trees/a826df48452256f195171155e75835d2bd14803ac6fd9b057ee8ae0a57b6c93f/qlib_bin/calendars/day.txt" --output-root "$sealed/artifacts/v2/free_evidence_funnel"
