#!/usr/bin/env bash
set -euo pipefail

repo_root=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)
config_root=${XDG_CONFIG_HOME:-"$HOME/.config"}
systemd_root="$config_root/systemd/user"
quant_root="$config_root/quant-stack"
if [[ "${1:-}" == "--preview" ]]; then
  printf 'Repository: %s\nUnits: %s\nEnvironment: %s\n' \
    "$repo_root" "$systemd_root" "$quant_root/prospective.env"
  exit 0
fi
mkdir -p "$systemd_root" "$quant_root"
cp "$repo_root/systemd/user/quant-prospective.service" "$systemd_root/"
cp "$repo_root/systemd/user/quant-prospective.timer" "$systemd_root/"
cp "$repo_root/systemd/user/quant-paper-failure@.service" "$systemd_root/"
if [[ ! -f "$quant_root/prospective.env" ]]; then
  sed \
    -e "s|/absolute/path/to/quan|$repo_root|g" \
    -e "s|/absolute/path/to/uv|$repo_root/.tools/uv/uv|g" \
    "$repo_root/systemd/prospective.env.example" > "$quant_root/prospective.env"
fi
systemctl --user daemon-reload
printf 'Installed prospective units and environment.\n'
