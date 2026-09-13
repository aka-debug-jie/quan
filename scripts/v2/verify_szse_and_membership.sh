#!/usr/bin/env bash
# Ordinary-user entrypoint. Only the fixed final replay requires sudo.
set -euo pipefail
task_repo=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)
cd "$task_repo"
sha256sum --check --status <<'HASHES'
21cddd9ba67b031883be84453474d2b44e321c268a08b0562e02a6e6b2f5771a  src/quant_stack_v2/szse_history.py
d62094919430405357bb5f1b2e238addc4ad06f162570b9141f8a007b1d9f202  src/quant_stack_v2/szse_history_verification.py
0bcd5b5f1e14cbcafe015613b89fe049de8806880658840398fd07ca194eeb44  src/quant_stack_v2/szse_issuer_supplement.py
4d052a3c281aaa1f34dad64b39c44619b492c4cfa12c754b758aa8c31d745889  src/quant_stack_v2/szse_monthly.py
3dee968f663b2bbb5c446108ed88c718c18d0931eccd2c4bedbf21bbf930e9e6  src/quant_stack_v2/szse_verification.py
267da4f7d6f162b87058a784c07dfcefeae7a5eda6b30c5add28f7261b9756d3  artifacts/v2/szse_history_evidence/267da4f7d6f162b87058a784c07dfcefeae7a5eda6b30c5add28f7261b9756d3.json
b94bb7fc7fa2f14ee7b87ee5f2cf44d1479fcda7500762bb57fb4d9d2611bbd2  artifacts/v2/szse_issuer_notice_evidence/b94bb7fc7fa2f14ee7b87ee5f2cf44d1479fcda7500762bb57fb4d9d2611bbd2.json
c64d2a14d863d7469e88a7fcf958e3b87b488b137de234bddd226a6477ee4367  src/quant_stack_v2/szse_lifecycle.py
3ac2dbd5ce391810ec51a5e10b4d4646afaad48f0ca5a3cefc06da0e9fc9ff09  artifacts/v2/szse_lifecycle_evidence/3ac2dbd5ce391810ec51a5e10b4d4646afaad48f0ca5a3cefc06da0e9fc9ff09.json
01b5b724ced7d8b48643d376f47257996b87017a6537b8e79f9fb55002153e88  scripts/v2/export_csi_anomaly_intervals.py
HASHES
task_base=/srv/quant-v2/sealed_holdout/artifacts/v2/free_suspension
task_output=$(mktemp /tmp/quant-szse-final.XXXXXX.json)
task_rc=0
sudo env PYTHONPATH="$task_repo/src" PYTHONDONTWRITEBYTECODE=1 \
  /srv/quant-v2/results/runtime/bin/python -m quant_stack_v2.szse_history_verification \
  --report "$task_base/szse_monthly_verification/b31fc67f7707cb728f1606b45ce909e0d1907991e62075be050b95a3ad186873.json" \
  --issuer "$task_repo/artifacts/v2/szse_issuer_notice_evidence/b94bb7fc7fa2f14ee7b87ee5f2cf44d1479fcda7500762bb57fb4d9d2611bbd2.json" \
  --history "$task_repo/artifacts/v2/szse_history_evidence/267da4f7d6f162b87058a784c07dfcefeae7a5eda6b30c5add28f7261b9756d3.json" \
  --lifecycle "$task_repo/artifacts/v2/szse_lifecycle_evidence/3ac2dbd5ce391810ec51a5e10b4d4646afaad48f0ca5a3cefc06da0e9fc9ff09.json" \
  --output-root "$task_base/szse_history_verification" > "$task_output" || task_rc=$?
if [[ ! -s "$task_output" ]]; then
  printf 'Replay failed before producing a summary (exit %s).\n' "$task_rc" >&2
  exit "$task_rc"
fi
printf 'Replay summary saved: %s\n' "$task_output"
printf 'Exit 1 is expected while either gap or PIT membership gate remains BLOCKED_DATA.\n'
task_members=$(mktemp /tmp/quant-csi-members.XXXXXX.json)
sudo /usr/bin/python3 -I -S -c '
import hashlib, sys
p = sys.argv[1]
b = open(p, "rb").read()
if hashlib.sha256(b).hexdigest() != "01b5b724ced7d8b48643d376f47257996b87017a6537b8e79f9fb55002153e88":
    raise SystemExit("member export script hash mismatch")
exec(compile(b, p, "exec"), {"__name__": "__main__"})
' "$task_repo/scripts/v2/export_csi_anomaly_intervals.py" > "$task_members"
printf 'Member interval summary saved: %s\n' "$task_members"
exit "$task_rc"
