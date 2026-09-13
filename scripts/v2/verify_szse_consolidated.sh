#!/usr/bin/env bash
# Ordinary-user entrypoint. Only the fixed final replay requires sudo.
set -euo pipefail
task_repo=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)
cd "$task_repo"
sha256sum --check --status <<'HASHES'
6d623a2f37b5c9bbea72366ca4ae5dd7522f149edc5c9dcd37f010a6ce254582  src/quant_stack_v2/szse_history.py
5aef28a7083f9fd84f20ff0d33bc27bb4880665dfa1fea1751d791edfcc77fe8  src/quant_stack_v2/szse_history_verification.py
0bcd5b5f1e14cbcafe015613b89fe049de8806880658840398fd07ca194eeb44  src/quant_stack_v2/szse_issuer_supplement.py
4d052a3c281aaa1f34dad64b39c44619b492c4cfa12c754b758aa8c31d745889  src/quant_stack_v2/szse_monthly.py
3dee968f663b2bbb5c446108ed88c718c18d0931eccd2c4bedbf21bbf930e9e6  src/quant_stack_v2/szse_verification.py
2cd45380d1da5b7d43cdfc6116bb12df36e827c02fc3f199e132e76875852ca8  artifacts/v2/szse_history_evidence/2cd45380d1da5b7d43cdfc6116bb12df36e827c02fc3f199e132e76875852ca8.json
b94bb7fc7fa2f14ee7b87ee5f2cf44d1479fcda7500762bb57fb4d9d2611bbd2  artifacts/v2/szse_issuer_notice_evidence/b94bb7fc7fa2f14ee7b87ee5f2cf44d1479fcda7500762bb57fb4d9d2611bbd2.json
HASHES
task_base=/srv/quant-v2/sealed_holdout/artifacts/v2/free_suspension
task_output=$(mktemp /tmp/quant-szse-final.XXXXXX.json)
task_rc=0
sudo env PYTHONPATH="$task_repo/src" PYTHONDONTWRITEBYTECODE=1 \
  /srv/quant-v2/results/runtime/bin/python -m quant_stack_v2.szse_history_verification \
  --report "$task_base/szse_monthly_verification/b31fc67f7707cb728f1606b45ce909e0d1907991e62075be050b95a3ad186873.json" \
  --issuer "$task_repo/artifacts/v2/szse_issuer_notice_evidence/b94bb7fc7fa2f14ee7b87ee5f2cf44d1479fcda7500762bb57fb4d9d2611bbd2.json" \
  --history "$task_repo/artifacts/v2/szse_history_evidence/2cd45380d1da5b7d43cdfc6116bb12df36e827c02fc3f199e132e76875852ca8.json" \
  --output-root "$task_base/szse_history_verification" > "$task_output" || task_rc=$?
if [[ ! -s "$task_output" ]]; then
  printf 'Replay failed before producing a summary (exit %s).\n' "$task_rc" >&2
  exit "$task_rc"
fi
printf 'Replay summary saved: %s\n' "$task_output"
printf 'Exit 1 is expected while either gap or PIT membership gate remains BLOCKED_DATA.\n'
exit "$task_rc"
