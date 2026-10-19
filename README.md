# AC Controller for Ubuntu

A native Python/GTK app for discovering and controlling Gree-compatible ACs on
your local network. A background service keeps device status current; the top-bar
menu and desktop window control each AC independently.

## Install

On Ubuntu GNOME, run as your normal desktop user:

```bash
./scripts/install.sh --install-deps
```

The installer uses `sudo` for Ubuntu packages, then installs the app in
`~/.local/share/gree-ac/venv`, creates a launcher at `~/.local/bin/gree-ac`, and
enables two user services. It starts discovery immediately. Discovery and startup
do not change your AC settings. The installer requires internet access for packages.

Open **AC Controller** from Applications, or run:

```bash
~/.local/bin/gree-ac
```

Use `./scripts/install.sh` when dependencies are already installed. Add `--no-start`
to install and enable the services without starting them in the current session.
Rerun the installer to install changes from this checkout.

If Ubuntu already has the indicator runtime library but lacks its Python metadata,
the installer downloads Ubuntu's typelib package and places just the metadata in
the app's private directory. This fallback does not require sudo.

## Controls

- The top-bar snowflake menu lists each AC, its power state, and target temperature.
  Open a device's submenu to change power or settings.
- The window shows all discovered ACs. Select one for power, mode, target
  temperature, temperature units, fan speed, and horizontal/vertical swing.
- Changes send immediately, except the window's temperature field: press **Set**
  to apply it. Pending changes disable controls until the device responds.
- **Set name…** appears next to the selected AC's name in the window and in each
  AC's top-bar submenu. Names update immediately in both places and survive
  service restarts and IP address changes. Leave the name blank to restore the
  device's original name. Names are stored locally for your Ubuntu user.
- **Add by IP** searches a specific IPv4 address and remembers it for future scans.
- Device status refreshes every 10 seconds. Discovery repeats every 60 seconds.
  Remembered devices remain listed while offline and are retried automatically.
- Closing the window leaves the top-bar menu running. **Quit desktop app** exits
  the interface; the background service continues until stopped or logged out.

The service and menu start when you log in. The menu follows your graphical
session; no root service or login-screen UI is installed. Each Ubuntu user has
their own service, device names, and desktop instance. No web server is exposed.

## Device requirements

Your AC must already be joined to Wi-Fi and support the local protocol implemented
by `greeclimate`. Automatic discovery uses IPv4 subnet broadcasts; devices on a
separate VLAN or behind client isolation may require network configuration or
manual IP entry. The protocol normally uses UDP port 7000. Not every Gree-branded
device or every setting is supported by every model.

Swing controls are enabled only after the AC reports those fields. Temperature
limits follow greeclimate (8–30 °C / 46–86 °F); individual ACs may impose tighter
limits. A command is followed by a fresh status request. If the AC returns different
settings, the app displays its reported state and an error instead of claiming success.

## Service management

```bash
systemctl --user status gree-ac.service gree-ac-indicator.service
journalctl --user -u gree-ac.service -f
systemctl --user restart gree-ac.service
systemctl --user stop gree-ac-indicator.service gree-ac.service
```

If the top-bar icon is missing, check that **Ubuntu AppIndicators** is enabled
in the GNOME Extensions app. After installing the extension for the first time,
logging out and back in may be necessary. The window remains usable if indicator
libraries are missing and shows the required package name.

Device identities, IP addresses, and friendly names are saved atomically in
`~/.config/gree-ac/devices.json` with permissions `0600`. The app binds again when
connecting and does not save binding keys. Standard XDG config/data directories
are respected.

## Development and simulation

Use Ubuntu's system Python so the GTK bindings match its Python version:

```bash
/usr/bin/python3 -m venv --system-site-packages .venv
.venv/bin/python -m pip install -e .
.venv/bin/python -m gree_ac service
# In another terminal in the same desktop session:
.venv/bin/python -m gree_ac desktop
```

To preview two simulated devices without communicating with real ACs, use a
private D-Bus session. Close the demo window and choose **Quit desktop app** to exit:

```bash
dbus-run-session -- sh -c '
  .venv/bin/python -m gree_ac service --demo --config /tmp/gree-ac-demo.json &
  service_pid=$!
  trap "kill $service_pid; wait $service_pid" EXIT
  .venv/bin/python -m gree_ac desktop
'
```

The window and menu explicitly label simulated devices. The original
`ac_controller.py` remains available as a one-shot terminal information table.

Run tests:

```bash
.venv/bin/python -m unittest discover -s tests -v
```

Tests cover validation, persistence, reconnection, command confirmation,
per-device serialization, a loopback UDP AC simulator, and service IPC on a private
D-Bus session. They never control physical ACs. GTK smoke tests also run when a
display is available.

## Uninstall

```bash
./scripts/uninstall.sh
```

This removes the installed app and services while preserving saved device names.
