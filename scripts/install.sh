#!/usr/bin/env bash
set -euo pipefail

project_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
install_dependencies=false
start_services=true
for argument in "$@"; do
    case "$argument" in
        --install-deps) install_dependencies=true ;;
        --no-start) start_services=false ;;
        *) printf 'Usage: %s [--install-deps] [--no-start]\n' "$0"; exit 2 ;;
    esac
done
if [ "$(id -u)" -eq 0 ]; then
    echo 'Run this installer as your desktop user. It uses sudo only for Ubuntu packages.' >&2
    exit 1
fi
if "$install_dependencies"; then
    sudo apt-get update
    sudo apt-get install -y python3-venv python3-gi gir1.2-gtk-3.0 gir1.2-ayatanaappindicator3-0.1
    if [ ! -d /usr/share/gnome-shell/extensions/ubuntu-appindicators@ubuntu.com ]; then
        if apt-cache show gnome-shell-ubuntu-extensions >/dev/null 2>&1; then
            sudo apt-get install -y gnome-shell-ubuntu-extensions
        else
            sudo apt-get install -y gnome-shell-extension-appindicator
        fi
    fi
fi
app_dir="${XDG_DATA_HOME:-$HOME/.local/share}/gree-ac"
mkdir -p -- "$app_dir"
/usr/bin/python3 - <<'PY'
try:
    import gi
    gi.require_version('Gtk', '3.0')
except (ImportError, ValueError) as exc:
    raise SystemExit(f'{exc}\nInstall Ubuntu dependencies with: ./scripts/install.sh --install-deps')
PY
export GI_TYPELIB_PATH="$app_dir/typelibs${GI_TYPELIB_PATH:+:$GI_TYPELIB_PATH}"
if ! /usr/bin/python3 -c 'import gi; gi.require_version("AyatanaAppIndicator3", "0.1")' 2>/dev/null; then
    # Ubuntu can ship the runtime library without Python's tiny typelib package.
    # Install just that metadata privately when no system package changes are needed.
    if ! /usr/bin/python3 -c 'import ctypes; ctypes.CDLL("libayatana-appindicator3.so.1")' 2>/dev/null; then
        echo 'Install indicator dependencies with: ./scripts/install.sh --install-deps' >&2
        exit 1
    fi
    staging_dir="$(mktemp -d)"
    trap 'rm -rf -- "$staging_dir"' EXIT
    (cd -- "$staging_dir" && apt-get download gir1.2-ayatanaappindicator3-0.1)
    dpkg-deb --extract "$staging_dir"/*.deb "$staging_dir/unpacked"
    mkdir -p -- "$app_dir/typelibs"
    find "$staging_dir/unpacked/usr/lib" -name 'AyatanaAppIndicator3-0.1.typelib' \
        -exec cp -- '{}' "$app_dir/typelibs/" \;
    /usr/bin/python3 -c 'import gi; gi.require_version("AyatanaAppIndicator3", "0.1")'
fi
/usr/bin/python3 -m venv --system-site-packages "$app_dir/venv"
"$app_dir/venv/bin/python" -m pip --disable-pip-version-check --no-input install "$project_dir"
"$app_dir/venv/bin/python" "$project_dir/scripts/integrate.py" "$app_dir" "$project_dir/packaging"
systemctl --user daemon-reload
systemctl --user enable gree-ac.service gree-ac-indicator.service
if "$start_services"; then
    systemctl --user restart gree-ac.service
    if systemctl --user is-active --quiet graphical-session.target; then
        systemctl --user restart gree-ac-indicator.service
    fi
fi
printf '\nInstalled AC Controller. Open it from Applications, or run:\n  %s/.local/bin/gree-ac\n' "$HOME"
