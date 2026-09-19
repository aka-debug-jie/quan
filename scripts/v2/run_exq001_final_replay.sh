#!/usr/bin/env bash
set -euo pipefail

if [[ ${EUID} -ne 0 ]]; then
  echo "run as root: sudo bash scripts/v2/run_exq001_final_replay.sh" >&2
  exit 2
fi

repo_root=/media/hgdl1012/84f6bd42-d506-47ff-8bf3-7b354ba37618/media/hgdl1012/program/quan
development_root=/srv/quant-v2/development
sealed_root=/srv/quant-v2/sealed_holdout
legacy_sha=d76df75580daaebcba9ca918c9854aa255d37f5d0d88c3cfeef71f2ee39d7862
raw_probe_sha=7315f8bea9e3906cb79947f81e60a320fd5d603eb7ff2b588b89f1a0a3333b48
history_sha=620b349f766c7afabeebaaad2ae26911e257215c749154785022f6c2b678ccf2
legacy="$development_root/exq001/candidate_scope_qualification/$legacy_sha.json"
raw_probe="$development_root/exq001/qlib_raw_probe/$raw_probe_sha.json"
history="$repo_root/artifacts/v2/exq_history_revalidation_20260919/$history_sha.json"
result_root="$development_root/exq001_final_replay"

export PYTHONPATH="$repo_root/src"
compiled=$(
  "$repo_root/.venv/bin/python" -m quant_stack_v2.exq_current_evidence_compile \
    --development-root "$development_root" \
    --sealed-root "$sealed_root" \
    --repo-root "$repo_root" \
    --registry "$repo_root/configs/v2/qualification/exq_001_candidate_scope_v1.yaml" \
    --raw-probe "$raw_probe" --raw-probe-sha256 "$raw_probe_sha" \
    --history "$history" --history-sha256 "$history_sha" \
    --corporate-ledger "$repo_root/configs/v2/qualification/exq_001_corporate_ledger_v1.yaml" \
    --result-root "$result_root"
)
compiled_sha=$(printf '%s' "$compiled" | "$repo_root/.venv/bin/python" -c 'import json,sys; print(json.load(sys.stdin)["compiled_scope_sha256"])')
compiled_path="$result_root/compiled_scope/$compiled_sha.json"

first=$("$repo_root/.venv/bin/python" -m quant_stack_v2.exq_candidate_replay \
  --compiled-scope "$compiled_path" --compiled-scope-sha256 "$compiled_sha" \
  --legacy-qualification "$legacy" --legacy-qualification-sha256 "$legacy_sha" \
  --result-root "$result_root")
second=$("$repo_root/.venv/bin/python" -m quant_stack_v2.exq_candidate_replay \
  --compiled-scope "$compiled_path" --compiled-scope-sha256 "$compiled_sha" \
  --legacy-qualification "$legacy" --legacy-qualification-sha256 "$legacy_sha" \
  --result-root "$result_root")
if [[ "$first" != "$second" ]]; then
  echo "non-deterministic EXQ final replay" >&2
  exit 1
fi
printf '%s\n' "$first"
