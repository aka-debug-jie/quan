#!/usr/bin/env bash
set -euo pipefail

systemctl --user enable --now quant-prospective.timer
systemctl --user list-timers quant-prospective.timer --no-pager
