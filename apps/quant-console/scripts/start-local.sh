#!/usr/bin/env bash
set -euo pipefail

if [[ $# -ne 4 ]]; then
  echo "usage: $0 SOURCE_CONFIG RUNTIME_DIR PYTHON_ENV STATIC_DIR" >&2
  exit 2
fi

source_config=$1
runtime_dir=$2
python_env=$3
static_dir=$4

"${python_env}/bin/quant-console" observe-system \
  --output "${runtime_dir}/system-observation.json"
"${python_env}/bin/quant-console" index \
  --config "${source_config}" \
  --runtime "${runtime_dir}"
exec "${python_env}/bin/quant-console" serve \
  --runtime "${runtime_dir}" \
  --config "${source_config}" \
  --static "${static_dir}" \
  --port 8765
