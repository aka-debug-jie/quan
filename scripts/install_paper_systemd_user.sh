#!/usr/bin/env bash
set -euo pipefail

repo_root=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)
config_root=${XDG_CONFIG_HOME:-"$HOME/.config"}
systemd_root="$config_root/systemd/user"
paper_root="$config_root/quant-stack"
if [[ "${1:-}" == "--preview" ]]; then
  printf 'Repository: %s\nUnits: %s\nEnvironment: %s\n' \
    "$repo_root" "$systemd_root" "$paper_root/paper.env"
  exit 0
fi
mkdir -p "$systemd_root" "$paper_root"
cp "$repo_root/systemd/user/quant-paper.service" "$systemd_root/"
cp "$repo_root/systemd/user/quant-paper.timer" "$systemd_root/"
cp "$repo_root/systemd/user/quant-paper-failure@.service" "$systemd_root/"
if [[ ! -f "$paper_root/paper.env" ]]; then
  sed \
    -e "s|/absolute/path/to/quan|$repo_root|g" \
    "$repo_root/systemd/paper.env.example" > "$paper_root/paper.env"
fi
systemctl --user daemon-reload
printf 'Installed without enabling the timer. Review %s, then run:\n' "$paper_root/paper.env"
printf '  bash %s/scripts/enable_paper_systemd_user.sh\n' "$repo_root"
