#!/usr/bin/env bash
set -euo pipefail

repo_root=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)
config_root=${XDG_CONFIG_HOME:-"$HOME/.config"}
systemd_root="$config_root/systemd/user"
paper_root="$config_root/quant-stack"
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
systemctl --user enable --now quant-paper.timer
