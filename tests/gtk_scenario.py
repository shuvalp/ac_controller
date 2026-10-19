"""Real GTK widgets connected to simulated devices over a private D-Bus session."""

import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import gi
gi.require_version("Gtk", "3.0")
gi.require_version("Gdk", "3.0")
from gi.repository import Gdk, GLib, Gtk

from gree_ac.desktop import Application


def wait_for(predicate, message):
    deadline = time.monotonic() + 8
    context = GLib.MainContext.default()
    while time.monotonic() < deadline:
        while context.pending():
            context.iteration(False)
        if predicate():
            return
        time.sleep(0.01)
    raise AssertionError(message)


def fill_name_dialog(value):
    def fill():
        dialog = next((window for window in Gtk.Window.list_toplevels()
                       if isinstance(window, Gtk.Dialog) and window.get_visible()), None)
        if dialog is None:
            return GLib.SOURCE_CONTINUE
        entry = next(child for child in dialog.get_content_area().get_children()
                     if isinstance(child, Gtk.Entry))
        entry.set_text(value)
        dialog.response(Gtk.ResponseType.OK)
        return GLib.SOURCE_REMOVE
    GLib.timeout_add(20, fill)


def main():
    assert Gtk.init_check()[0], "Could not connect to the graphical display"
    with tempfile.TemporaryDirectory() as directory:
        process = subprocess.Popen([sys.executable, "-m", "gree_ac", "service", "--demo",
                                    "--config", str(Path(directory) / "devices.json")],
                                   stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        app = Application()
        try:
            assert app.register(None)
            app.activate()
            wait_for(lambda: len(app.client.snapshot["devices"]) == 2
                     and all(device["online"] for device in app.client.snapshot["devices"]),
                     "Device list never became ready")
            assert len(app.window.list_store) == 2
            app.open_device("demo01")
            assert app.window.panel.device["id"] == "demo01"
            assert app.window.panel.power.get_active()
            app.window.panel.power.set_active(False)
            wait_for(lambda: not app.busy and app.window.panel.device["state"]["power"] is False,
                     "Window power switch failed")
            app.window.panel.temperature.set_value(22)
            app.window.panel.apply_temperature.clicked()
            wait_for(lambda: not app.busy and app.window.panel.device["state"]["target_temperature"] == 22,
                     "Window temperature control failed")
            app.window.panel.controls["mode"].set_active_id("4")
            wait_for(lambda: not app.busy and app.window.panel.device["state"]["mode"] == 4,
                     "Window mode control failed")
            if app.indicator:
                original_items = app.menu.get_children()
                app._snapshot(app.client.snapshot)
                assert app.menu.get_children() == original_items, "Unchanged status rebuilt an open menu"
                parent = next(item for item in app.menu.get_children()
                              if item.get_label() and item.get_label().startswith("Living room"))
                submenu = parent.get_submenu()
                power = next(item for item in submenu.get_children() if item.get_label() == "Power on")
                power.activate()
                wait_for(lambda: not app.busy and app.window.panel.device["state"]["power"] is True,
                         "Top-bar power control failed")
            else:
                assert app.indicator_warning
            fill_name_dialog("Lounge")
            app.window.panel.name_button.clicked()
            wait_for(lambda: app.window.panel.device["name"] == "Lounge", "Window naming failed")
            assert app.window.panel.title.get_text() == "Lounge"
            assert any(row[1] == "Lounge" for row in app.window.list_store)
            if app.indicator:
                bedroom = next(item for item in app.menu.get_children()
                               if item.get_label() and item.get_label().startswith("Bedroom"))
                rename = next(item for item in bedroom.get_submenu().get_children()
                              if item.get_label() == "Set name…")
                fill_name_dialog("Guest room")
                rename.activate()
                wait_for(lambda: any(device["id"] == "demo02" and device["name"] == "Guest room"
                                     for device in app.client.snapshot["devices"]), "Menu naming targeted the wrong AC")
                assert app.window.panel.device["name"] == "Lounge"
                assert any(item.get_label() and item.get_label().startswith("Lounge")
                           for item in app.menu.get_children())
            fill_name_dialog("")
            app.window.panel.name_button.clicked()
            wait_for(lambda: app.window.panel.device["name"] == "Living room", "Resetting a custom name failed")
            assert not app.last_error, app.last_error
            artifact = os.environ.get("GREE_AC_SCREENSHOT")
            if artifact:
                import cairo
                width, height = app.window.get_allocated_width(), app.window.get_allocated_height()
                surface = cairo.ImageSurface(cairo.FORMAT_ARGB32, width, height)
                context = cairo.Context(surface)
                app.window.draw(context)
                surface.write_to_png(artifact)
            print("GTK window and menu integration passed")
        finally:
            if app.window:
                app.window.destroy()
            app.quit()
            process.terminate()
            output, error = process.communicate(timeout=10)
            if process.returncode != 0:
                raise AssertionError(f"Service failed ({process.returncode})\n{output}\n{error}")


if __name__ == "__main__":
    main()
