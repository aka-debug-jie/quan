#!/usr/bin/env bash
set -euo pipefail

app_root=$(cd "$(dirname "$0")/.." && pwd)
temporary=$(mktemp -d /tmp/quant-console-contract.XXXXXX)
trap 'rm -rf "${temporary}"' EXIT

uv run --project "${app_root}/backend" quant-console openapi \
  --output "${temporary}/openapi.json"
cmp "${app_root}/frontend/openapi.json" "${temporary}/openapi.json"

"${app_root}/frontend/node_modules/.bin/openapi-typescript" \
  "${temporary}/openapi.json" \
  -o "${temporary}/api-schema.ts"
cmp "${app_root}/frontend/src/generated/api-schema.ts" \
  "${temporary}/api-schema.ts"

echo "Quant Console OpenAPI and generated TypeScript contracts are current."

