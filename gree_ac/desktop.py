"""Native GTK window and AppIndicator menu for the background controller."""

import json
from pathlib import Path
import time

import gi

gi.require_version("Gtk", "3.0")
gi.require_version("Gdk", "3.0")
from gi.repository import Gdk, Gio, GLib, Gtk, Pango

from .client import Client
from .model import (
    APP_ID, CHOICES, FAN_SPEEDS, HORIZONTAL_SWING, MODES, VERTICAL_SWING,
    power_text, temperature_bounds, temperature_text,
)

ICON = str(Path(__file__).with_name("assets") / "gree-ac-symbolic.svg")


def menu_item(menu, label, callback=None, sensitive=True):
    item = Gtk.MenuItem(label=label, use_underline=False)
    item.set_sensitive(sensitive)
    if callback:
        item.connect("activate", lambda *_: callback())
    menu.append(item)
    return item


class DevicePanel(Gtk.Box):
    def __init__(self, app):
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=14, margin=24)
        self.app, self.device, self.updating = app, None, False
        self.temperature_dirty = False
        name_row = Gtk.Box(spacing=10)
        self.title = Gtk.Label(xalign=0, ellipsize=Pango.EllipsizeMode.END)
        self.title.get_style_context().add_class("device-title")
        name_row.pack_start(self.title, True, True, 0)
        self.name_button = Gtk.Button(label="Set name…", valign=Gtk.Align.CENTER)
        self.name_button.connect("clicked", lambda *_: app.rename_device(self.device))
        name_row.pack_end(self.name_button, False, False, 0)
        self.pack_start(name_row, False, False, 0)
        self.description = Gtk.Label(xalign=0, selectable=True, wrap=True)
        self.description.get_style_context().add_class("dim-label")
        self.pack_start(self.description, False, False, 0)
        self.room = Gtk.Label(xalign=0)
        self.room.get_style_context().add_class("room-temperature")
        self.pack_start(self.room, False, False, 0)
        grid = Gtk.Grid(column_spacing=20, row_spacing=14)
        self.pack_start(grid, False, False, 0)
        self.controls = {}
        self.power = Gtk.Switch(halign=Gtk.Align.START)
        self.power.connect("notify::active", self._power_changed)
        self._row(grid, 0, "Power", self.power)
        self.controls["power"] = self.power
        for index, (field, title) in enumerate((("mode", "Mode"), ("fan_speed", "Fan speed")), 1):
            combo = self._combo(CHOICES[field])
            combo.connect("changed", self._choice_changed, field)
            self.controls[field] = combo
            self._row(grid, index, title, combo)
        temp_box = Gtk.Box(spacing=8)
        self.temperature = Gtk.SpinButton.new_with_range(8, 30, 1)
        self.temperature.set_numeric(True)
        self.temperature.connect("value-changed", self._temperature_changed)
        self.apply_temperature = Gtk.Button(label="Set")
        self.apply_temperature.connect("clicked", self._apply_temperature)
        temp_box.pack_start(self.temperature, True, True, 0)
        temp_box.pack_start(self.apply_temperature, False, False, 0)
        self._row(grid, 3, "Target temperature", temp_box)
        self.units = self._combo({0: "Celsius (°C)", 1: "Fahrenheit (°F)"})
        self.units.connect("changed", self._choice_changed, "temperature_units")
        self.controls["temperature_units"] = self.units
        self._row(grid, 4, "Units", self.units)
        for index, (field, title) in enumerate((
            ("horizontal_swing", "Horizontal swing"), ("vertical_swing", "Vertical swing"),
        ), 5):
            combo = self._combo(CHOICES[field])
            combo.connect("changed", self._choice_changed, field)
            self.controls[field] = combo
            self._row(grid, index, title, combo)
        self.status = Gtk.Label(xalign=0, wrap=True, selectable=True)
        self.pack_start(self.status, False, False, 0)
        help_text = Gtk.Label(label="Controls reflect the latest settings reported by the AC.\n"
                             "Unavailable swing controls are disabled.", xalign=0, wrap=True)
        help_text.get_style_context().add_class("dim-label")
        self.pack_end(help_text, False, False, 0)

    @staticmethod
    def _combo(choices):
        combo = Gtk.ComboBoxText(hexpand=True)
        for value, text in choices.items():
            combo.append(str(value), text)
        return combo

    @staticmethod
    def _row(grid, row, title, widget):
        grid.attach(Gtk.Label(label=title, xalign=0), 0, row, 1, 1)
        grid.attach(widget, 1, row, 1, 1)

    def _power_changed(self, switch, *_):
        if not self.updating and self.device:
            self.app.set_device(self.device["id"], {"power": switch.get_active()})

    def _choice_changed(self, combo, field):
        value = combo.get_active_id()
        if not self.updating and self.device and value is not None:
            self.app.set_device(self.device["id"], {field: int(value)})

    def _temperature_changed(self, *_):
        if not self.updating:
            self.temperature_dirty = True

    def _apply_temperature(self, *_):
        if self.device:
            self.temperature.update()
            self.temperature_dirty = False
            self.app.set_device(self.device["id"], {"target_temperature": self.temperature.get_value_as_int()})

    def update(self, device):
        same_device = self.device and self.device["id"] == device["id"]
        same_units = same_device and self.device["state"].get("temperature_units") == device["state"].get("temperature_units")
        if not same_units:
            self.temperature_dirty = False
        self.device, self.updating = device, True
        state = device["state"]
        available = self.app.client.connected and device["online"] and not self.app.is_busy(device)
        self.title.set_text(device["name"])
        self.title.set_tooltip_text(device["name"])
        self.name_button.set_sensitive(self.app.client.connected)
        self.description.set_text(f"{device['ip']}  ·  {device['id']}")
        self.room.set_text("Room  " + temperature_text(state.get("current_temperature"), state.get("temperature_units")))
        for field, control in self.controls.items():
            value = state.get(field)
            if field == "power":
                control.set_active(bool(value))
            else:
                control.set_active_id(str(value) if value is not None else None)
            control.set_sensitive(available and value is not None)
        lower, upper = temperature_bounds(state.get("temperature_units"))
        self.temperature.set_range(lower, upper)
        if not self.temperature_dirty:
            value = state.get("target_temperature")
            self.temperature.set_value(value if value is not None else lower)
        can_set_temp = (available and state.get("target_temperature") is not None
                        and state.get("temperature_units") in (0, 1))
        self.temperature.set_sensitive(can_set_temp)
        self.apply_temperature.set_sensitive(can_set_temp)
        if self.app.is_busy(device):
            message = "Sending change and waiting for the AC…"
        elif device["error"]:
            message = device["error"]
        elif not self.app.client.connected:
            message = "Service disconnected. Settings may be out of date."
        elif not device["online"]:
            message = "Offline — waiting for the device to reconnect."
        else:
            age = max(0, int(time.time() - device["last_seen"])) if device["last_seen"] else 0
            message = f"Connected · Updated {age} seconds ago"
        self.status.set_text(message)
        self.updating = False


class Window(Gtk.ApplicationWindow):
    def __init__(self, app):
        super().__init__(application=app, title="AC Controller")
        self.app = app
        self.set_default_size(1120, 640)
        self.set_icon_from_file(ICON)
        self.connect("delete-event", self._hide)
        header = Gtk.HeaderBar(title="AC Controller", subtitle="Your air conditioners, together", show_close_button=True)
        self.set_titlebar(header)
        self.scan_button = Gtk.Button(label="Scan for devices")
        self.scan_button.connect("clicked", lambda *_: app.scan())
        header.pack_start(self.scan_button)
        add_button = Gtk.Button(label="Add by IP…")
        add_button.connect("clicked", lambda *_: app.add_by_ip())
        header.pack_end(add_button)
        self.add_button = add_button
        outer = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        self.add(outer)
        self.error_bar = Gtk.InfoBar(message_type=Gtk.MessageType.ERROR, show_close_button=True, no_show_all=True)
        self.error_label = Gtk.Label(xalign=0, wrap=True, selectable=True)
        self.error_bar.get_content_area().add(self.error_label)
        self.error_label.show()
        self.error_bar.connect("response", lambda *_: self.error_bar.hide())
        outer.pack_start(self.error_bar, False, False, 0)
        self.service_bar = Gtk.Box(spacing=12, margin=12)
        self.connection_label = Gtk.Label(xalign=0, hexpand=True, wrap=True)
        self.start_button = Gtk.Button(label="Start service")
        self.start_button.connect("clicked", lambda *_: app.start_service())
        self.service_bar.pack_start(self.connection_label, True, True, 0)
        self.service_bar.pack_end(self.start_button, False, False, 0)
        outer.pack_start(self.service_bar, False, False, 0)
        self.indicator_note = Gtk.Label(xalign=0, wrap=True, margin_start=12, margin_end=12, no_show_all=True)
        outer.pack_start(self.indicator_note, False, False, 6)
        pane = Gtk.Paned(orientation=Gtk.Orientation.HORIZONTAL)
        outer.pack_start(pane, True, True, 0)
        self.list_store = Gtk.ListStore(*([str] * 8))
        self.tree = Gtk.TreeView(model=self.list_store, headers_visible=True)
        self.tree.set_enable_search(True)
        self.tree.set_search_column(1)
        for index, title in enumerate(("Device", "Power", "Mode", "Room", "Target", "Fan", "Status"), 1):
            renderer = Gtk.CellRendererText()
            column = Gtk.TreeViewColumn(title, renderer, text=index)
            column.set_resizable(True)
            column.set_sort_column_id(index)
            column.set_min_width(65 if index > 1 else 130)
            self.tree.append_column(column)
        self.tree.get_selection().connect("changed", self._selected)
        self.updating_list = False
        self.scroll = Gtk.ScrolledWindow()
        self.scroll.set_policy(Gtk.PolicyType.AUTOMATIC, Gtk.PolicyType.AUTOMATIC)
        self.scroll.add(self.tree)
        self.left_stack = Gtk.Stack()
        self.left_stack.add_named(self.scroll, "devices")
        empty = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=16, margin=32,
                        valign=Gtk.Align.CENTER, halign=Gtk.Align.CENTER)
        image = Gtk.Image.new_from_file(ICON)
        image.set_pixel_size(64)
        empty.pack_start(image, False, False, 0)
        empty.pack_start(Gtk.Label(label="No air conditioners discovered", xalign=0.5), False, False, 0)
        empty.pack_start(Gtk.Label(label="Connect to the same network as your ACs,\n"
                                  "then scan or add a device by IP address.", justify=Gtk.Justification.CENTER),
                         False, False, 0)
        self.left_stack.add_named(empty, "empty")
        pane.pack1(self.left_stack, True, False)
        self.detail_stack = Gtk.Stack()
        self.detail_stack.set_size_request(340, -1)
        self.panel = DevicePanel(app)
        details_scroll = Gtk.ScrolledWindow()
        details_scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        details_scroll.add(self.panel)
        self.detail_stack.add_named(details_scroll, "device")
        self.detail_stack.add_named(Gtk.Label(label="Select an AC to control it."), "empty")
        pane.pack2(self.detail_stack, False, False)
        pane.set_position(700)
        self.show_all()
        self.error_bar.hide()

    def _hide(self, *_):
        if not self.app.indicator:
            self.app.quit()
        else:
            self.hide()
        return True

    def show_error(self, message):
        self.error_label.set_text(message)
        self.error_bar.show()

    def _selected(self, selection):
        if self.updating_list:
            return
        model, tree_iter = selection.get_selected()
        self.app.selected_id = model[tree_iter][0] if tree_iter else None
        self.update_detail()

    def update_detail(self):
        selected = next((device for device in self.app.client.snapshot["devices"]
                         if device["id"] == self.app.selected_id), None)
        self.detail_stack.set_visible_child_name("device" if selected else "empty")
        if selected:
            self.panel.update(selected)

    def update(self, snapshot):
        self.updating_list = True
        self.list_store.clear()
        selected_iter = None
        for device in snapshot["devices"]:
            state = device["state"]
            status = "Sending…" if self.app.is_busy(device) else "Error" if device["error"] else "Online" if device["online"] else "Offline"
            if not self.app.client.connected:
                status = "Service unavailable"
            tree_iter = self.list_store.append([
                device["id"], device["name"], power_text(state.get("power")),
                MODES.get(state.get("mode"), "Unknown"),
                temperature_text(state.get("current_temperature"), state.get("temperature_units")),
                temperature_text(state.get("target_temperature"), state.get("temperature_units")),
                FAN_SPEEDS.get(state.get("fan_speed"), "Unknown"), status,
            ])
            if device["id"] == self.app.selected_id:
                selected_iter = tree_iter
        if snapshot["devices"] and selected_iter is None:
            selected_iter = self.list_store.get_iter_first()
            self.app.selected_id = self.list_store[selected_iter][0]
        if selected_iter is not None:
            self.tree.get_selection().select_iter(selected_iter)
        self.updating_list = False
        self.left_stack.set_visible_child_name("devices" if snapshot["devices"] else "empty")
        self.scan_button.set_sensitive(self.app.client.connected and not snapshot["scanning"])
        self.add_button.set_sensitive(self.app.client.connected and not snapshot["scanning"])
        self.scan_button.set_label("Scanning…" if snapshot["scanning"] else "Scan for devices")
        count = len(snapshot["devices"])
        online = sum(device["online"] for device in snapshot["devices"])
        if not self.app.client.connected:
            text = "Background service is unavailable. Start it to discover and control ACs."
        elif snapshot["demo"]:
            text = "SIMULATION · These devices are local examples. No real ACs are controlled."
        else:
            text = f"{count} device(s) · {online} online · Status refreshes every 10 seconds"
        self.connection_label.set_text(text)
        self.start_button.set_visible(not self.app.client.connected)
        if self.app.indicator_warning:
            self.indicator_note.set_text(self.app.indicator_warning)
            self.indicator_note.show()
        self.update_detail()


class Application(Gtk.Application):
    def __init__(self):
        super().__init__(application_id=APP_ID, flags=Gio.ApplicationFlags.HANDLES_COMMAND_LINE)
        self.window = None
        self.indicator = None
        self.indicator_warning = ""
        self.selected_id = None
        self.busy = set()
        self.last_error = ""
        self.client = None
        self.menu_signature = None

    def do_startup(self):
        Gtk.Application.do_startup(self)
        self.hold()
        provider = Gtk.CssProvider()
        provider.load_from_data(b".device-title { font-size: 22px; font-weight: bold; } "
                                b".room-temperature { font-size: 19px; } treeview { padding: 6px; }")
        Gtk.StyleContext.add_provider_for_screen(Gdk.Screen.get_default(), provider, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)
        self._create_indicator()
        self.client = Client(self._snapshot, self.show_error)

    def do_activate(self):
        self.present_window()

    def do_command_line(self, command_line):
        arguments = command_line.get_arguments()[1:]
        if "--quit" in arguments:
            self.quit()
        elif "--indicator" not in arguments or not self.indicator:
            self.present_window()
        return 0

    def do_shutdown(self):
        if self.indicator:
            self.indicator.set_status(self.indicator_module.IndicatorStatus.PASSIVE)
        Gtk.Application.do_shutdown(self)

    def _create_indicator(self):
        module = None
        for namespace in ("AyatanaAppIndicator3", "AppIndicator3"):
            try:
                gi.require_version(namespace, "0.1")
                import importlib
                module = importlib.import_module("gi.repository." + namespace)
                break
            except (ValueError, ImportError):
                continue
        if module is None:
            self.indicator_warning = "Top-bar support is missing. Install gir1.2-ayatanaappindicator3-0.1, then restart the app."
            return
        self.indicator_module = module
        self.indicator = module.Indicator.new("gree-ac-controller", ICON, module.IndicatorCategory.HARDWARE)
        self.indicator.set_title("AC Controller")
        self.indicator.set_status(module.IndicatorStatus.ACTIVE)
        self.menu = Gtk.Menu()
        menu_item(self.menu, "Connecting to AC service…", sensitive=False)
        self.menu.show_all()
        self.indicator.set_menu(self.menu)

    def present_window(self):
        if self.window is None:
            self.window = Window(self)
        if self.client:
            self.window.update(self.client.snapshot)
        if self.last_error:
            self.window.show_error(self.last_error)
        self.window.present()

    def show_error(self, message):
        self.last_error = message
        self.present_window()
        self.window.show_error(message)

    def is_busy(self, device):
        return device["pending"] or device["id"] in self.busy

    def _snapshot(self, snapshot):
        if self.window:
            self.window.update(snapshot)
        if self.indicator:
            self._update_menu(snapshot)
        if snapshot["error"] and snapshot["error"] != self.last_error:
            self.show_error(snapshot["error"])

    def _choices_menu(self, menu, device, label, field, choices):
        parent = menu_item(menu, label, sensitive=device["state"].get(field) is not None)
        submenu = Gtk.Menu()
        parent.set_submenu(submenu)
        for value, title in choices.items():
            item = Gtk.CheckMenuItem(label=title, draw_as_radio=True, use_underline=False)
            item.set_active(device["state"].get(field) == value)
            item.connect("activate", lambda widget, value=value: self.set_device(device["id"], {field: value}))
            submenu.append(item)

    def _update_menu(self, snapshot):
        # A status poll changes timestamps even when every menu item is identical.
        # Keep open submenus intact during those routine refreshes.
        signature = json.dumps({
            "connected": self.client.connected,
            "demo": snapshot["demo"], "scanning": snapshot["scanning"],
            "busy": sorted(self.busy),
            "devices": [{key: value for key, value in device.items() if key != "last_seen"}
                        for device in snapshot["devices"]],
        }, sort_keys=True)
        if signature == self.menu_signature:
            return
        self.menu_signature = signature
        for child in self.menu.get_children():
            self.menu.remove(child)
        connected = self.client.connected
        title = "AC Controller · Simulation" if snapshot["demo"] else "AC Controller"
        menu_item(self.menu, title, sensitive=False)
        if not connected:
            menu_item(self.menu, "Service unavailable", sensitive=False)
            menu_item(self.menu, "Start service", self.start_service)
        if not snapshot["devices"]:
            menu_item(self.menu, "Scanning…" if snapshot["scanning"] else "No devices found", sensitive=False)
        for device in snapshot["devices"]:
            state = device["state"]
            label = f"{device['name']} · {power_text(state.get('power'))}"
            if state.get("power"):
                label += " · " + temperature_text(state.get("target_temperature"), state.get("temperature_units"))
            if not device["online"]:
                label += " · Offline"
            if self.is_busy(device):
                label += " · Sending…"
            parent = menu_item(self.menu, label)
            submenu = Gtk.Menu()
            parent.set_submenu(submenu)
            menu_item(submenu, "Room: " + temperature_text(state.get("current_temperature"), state.get("temperature_units")), sensitive=False)
            active = connected and device["online"] and not self.is_busy(device)
            power = Gtk.CheckMenuItem(label="Power on")
            power.set_active(bool(state.get("power")))
            power.set_sensitive(active and state.get("power") is not None)
            power.connect("activate", lambda item, device_id=device["id"]: self.set_device(device_id, {"power": item.get_active()}))
            submenu.append(power)
            controls = Gtk.Menu()
            control_item = menu_item(submenu, "Settings", sensitive=active)
            control_item.set_submenu(controls)
            self._choices_menu(controls, device, "Mode", "mode", MODES)
            self._choices_menu(controls, device, "Fan speed", "fan_speed", FAN_SPEEDS)
            units = state.get("temperature_units")
            lower, upper = temperature_bounds(units)
            self._choices_menu(controls, device, "Target temperature", "target_temperature", {
                value: temperature_text(value, units) for value in range(lower, upper + 1)
            })
            self._choices_menu(controls, device, "Horizontal swing", "horizontal_swing", HORIZONTAL_SWING)
            self._choices_menu(controls, device, "Vertical swing", "vertical_swing", VERTICAL_SWING)
            if device["error"]:
                menu_item(submenu, device["error"], sensitive=False)
            menu_item(submenu, "Open device…", lambda device_id=device["id"]: self.open_device(device_id))
            menu_item(submenu, "Set name…", lambda device=device: self.rename_device(device), sensitive=connected)
        self.menu.append(Gtk.SeparatorMenuItem())
        menu_item(self.menu, "Open all devices", self.present_window)
        menu_item(self.menu, "Scanning…" if snapshot["scanning"] else "Scan for devices",
                  self.scan, sensitive=connected and not snapshot["scanning"])
        menu_item(self.menu, "Add by IP…", self.add_by_ip, sensitive=connected and not snapshot["scanning"])
        self.menu.append(Gtk.SeparatorMenuItem())
        menu_item(self.menu, "Quit desktop app", self.quit)
        self.menu.show_all()

    def open_device(self, device_id):
        self.selected_id = device_id
        self.present_window()

    def set_device(self, device_id, settings):
        if device_id in self.busy:
            return
        self.busy.add(device_id)
        self._snapshot(self.client.snapshot)

        def finished(success):
            self.busy.discard(device_id)
            self._snapshot(self.client.snapshot)
        self.client.call("SetDevice", (device_id, json.dumps(settings)), finished)

    def scan(self):
        self.client.call("Scan", ("",))

    def _text_dialog(self, title, prompt, initial="", max_length=0):
        self.present_window()
        dialog = Gtk.Dialog(title=title, transient_for=self.window, modal=True)
        dialog.add_buttons("Cancel", Gtk.ResponseType.CANCEL, "Save", Gtk.ResponseType.OK)
        dialog.set_default_response(Gtk.ResponseType.OK)
        box = dialog.get_content_area()
        box.set_border_width(18)
        box.set_spacing(12)
        box.add(Gtk.Label(label=prompt, xalign=0, wrap=True))
        entry = Gtk.Entry(text=initial, activates_default=True, width_chars=35)
        entry.set_max_length(max_length)
        box.add(entry)
        dialog.show_all()
        entry.grab_focus()
        entry.select_region(0, -1)
        response = dialog.run()
        value = entry.get_text().strip() if response == Gtk.ResponseType.OK else None
        dialog.destroy()
        return value

    def add_by_ip(self):
        address = self._text_dialog("Add AC by IP", "Enter the AC's IPv4 address, for example 192.168.1.50.")
        if address:
            self.client.call("Scan", (address,))

    def rename_device(self, device):
        if device:
            name = self._text_dialog(
                "Set AC name", f"Name for the AC at {device['ip']}.\n"
                "Leave blank to use the device's original name.",
                device.get("custom_name", device["name"]), max_length=80,
            )
            if name is not None:
                self.client.call("RenameDevice", (device["id"], name))

    def start_service(self):
        try:
            process = Gio.Subprocess.new(["systemctl", "--user", "start", "gree-ac.service"],
                                         Gio.SubprocessFlags.STDOUT_PIPE | Gio.SubprocessFlags.STDERR_PIPE)

            def finished(proc, result, data):
                try:
                    _, output, error = proc.communicate_utf8_finish(result)
                    if not proc.get_successful():
                        self.show_error(error.strip() or "Could not start the service. Run the installer first.")
                except GLib.Error as exc:
                    self.show_error(str(exc))
            process.communicate_utf8_async(None, None, finished, None)
        except GLib.Error as exc:
            self.show_error(str(exc))


def main(indicator=False, quit_app=False):
    app = Application()
    arguments = ["gree-ac"]
    if indicator:
        arguments.append("--indicator")
    if quit_app:
        arguments.append("--quit")
    raise SystemExit(app.run(arguments))
