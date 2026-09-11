#!/usr/bin/env bash
set -euo pipefail

if [[ "${EUID}" -ne 0 ]]; then
  echo "run as root: sudo scripts/v2/setup_sealed_holdout.sh" >&2
  exit 1
fi

getent group quant-v2 >/dev/null || groupadd --system quant-v2
getent group quant-eval >/dev/null || groupadd --system quant-eval
id -u quant-research >/dev/null 2>&1 || useradd --system --no-create-home --gid quant-v2 --shell /usr/sbin/nologin quant-research
id -u quant-eval >/dev/null 2>&1 || useradd --system --no-create-home --gid quant-eval --groups quant-v2 --shell /usr/sbin/nologin quant-eval

install -d -o root -g root -m 0755 /srv/quant-v2
install -d -o quant-research -g quant-v2 -m 0750 /srv/quant-v2/development
install -d -o quant-research -g quant-v2 -m 0750 /srv/quant-v2/validation
install -d -o root -g root -m 0711 /srv/quant-v2/sealed_holdout
install -d -o root -g quant-eval -m 0750 /srv/quant-v2/sealed_holdout/data/external
install -d -o root -g quant-eval -m 0750 /srv/quant-v2/sealed_holdout/artifacts/v2
install -d -o quant-eval -g quant-eval -m 0700 /srv/quant-v2/sealed_holdout/attempts
install -d -o quant-eval -g quant-v2 -m 0750 /srv/quant-v2/results
install -o root -g root -m 0644 /dev/null /srv/quant-v2/sealed_holdout/SEALED_HOLDOUT_READY.json
printf '%s\n' '{"schema_version":1,"status":"READY"}' > /srv/quant-v2/sealed_holdout/SEALED_HOLDOUT_READY.json
