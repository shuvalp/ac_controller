#!/usr/bin/env bash
set -euo pipefail
if [ "$(id -u)" -eq 0 ]; then
    echo 'Run this as the desktop user who installed AC Controller.' >&2
    exit 1
fi
app_dir="${XDG_DATA_HOME:-$HOME/.local/share}/gree-ac"
config_dir="${XDG_CONFIG_HOME:-$HOME/.config}"
data_dir="${XDG_DATA_HOME:-$HOME/.local/share}"
systemctl --user disable --now gree-ac-indicator.service gree-ac.service || true
if [ -x "$HOME/.local/bin/gree-ac" ]; then
    "$HOME/.local/bin/gree-ac" --quit || true
fi
rm -f -- "$config_dir/systemd/user/gree-ac.service" "$config_dir/systemd/user/gree-ac-indicator.service" \
    "$data_dir/applications/gree-ac.desktop" "$HOME/.local/bin/gree-ac"
if [ -n "$app_dir" ] && [ "$app_dir" != / ]; then
    rm -rf -- "$app_dir"
fi
systemctl --user daemon-reload
echo 'AC Controller removed. Device names are preserved in your gree-ac configuration directory.'
