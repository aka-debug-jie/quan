#!/usr/bin/env bash
set -euo pipefail

: "${QUANT_STACK_REPO:?missing QUANT_STACK_REPO}"
: "${QUANT_STACK_UV:?missing QUANT_STACK_UV}"
: "${ALLOW_NETWORK:?missing ALLOW_NETWORK}"
cd "$QUANT_STACK_REPO"
if [[ "$ALLOW_NETWORK" != "1" ]]; then
  echo "automatic network access is not enabled" >&2
  exit 1
fi
exec "$QUANT_STACK_UV" run quant v2 prospective run-daily --allow-network
