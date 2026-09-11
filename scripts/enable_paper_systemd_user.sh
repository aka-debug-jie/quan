#!/usr/bin/env bash
set -euo pipefail

config_root=${XDG_CONFIG_HOME:-"$HOME/.config"}
environment_file="$config_root/quant-stack/paper.env"
if [[ ! -f "$environment_file" ]]; then
  echo "paper.env is not installed; run install_paper_systemd_user.sh first" >&2
  exit 1
fi
if ! grep -qx 'ALLOW_NETWORK=1' "$environment_file"; then
  echo "paper.env does not explicitly authorize automatic network access" >&2
  exit 1
fi
systemctl --user daemon-reload
systemctl --user enable --now quant-paper.timer
