#!/usr/bin/env bash
# Run as the ordinary user; sudo applies only to the hash-bound Python payload.
set -euo pipefail
task_repo=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)
task_export=$(mktemp /tmp/quant-szse-dates.XXXXXX.json)
sudo /usr/bin/python3 -I -S -c '
import hashlib, sys
p = sys.argv[1]
b = open(p, "rb").read()
if hashlib.sha256(b).hexdigest() != "e8a0f3d121c08e66be6b6a7a08fab9de5e6967ae05f6b0350dd0f1d806de38a7":
    raise SystemExit("export script hash mismatch")
exec(compile(b, p, "exec"), {"__name__": "__main__"})
' "$task_repo/scripts/v2/export_szse_matching_dates.py" > "$task_export"
printf 'Export completed: %s\n' "$task_export"
