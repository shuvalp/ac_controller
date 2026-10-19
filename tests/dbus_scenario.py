"""Standalone integration scenario, always launched on a private session bus."""

import json
from pathlib import Path
import subprocess
import sys
import tempfile
import time

from gi.repository import Gio, GLib

# Running a test file puts tests/, rather than the repository root, on sys.path.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from gree_ac.model import BUS_NAME, INTERFACE, OBJECT_PATH


def main():
    with tempfile.TemporaryDirectory() as directory:
        process = subprocess.Popen([sys.executable, "-m", "gree_ac", "service", "--demo",
                                    "--config", str(Path(directory) / "devices.json")],
                                   stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        try:
            bus = Gio.bus_get_sync(Gio.BusType.SESSION, None)

            def call(method, signature="()", args=()):
                result = bus.call_sync(BUS_NAME, OBJECT_PATH, INTERFACE, method,
                                       GLib.Variant(signature, args), GLib.VariantType.new("(s)"),
                                       Gio.DBusCallFlags.NONE, 10000, None)
                return json.loads(result.unpack()[0])

            deadline = time.monotonic() + 8
            while time.monotonic() < deadline:
                try:
                    snapshot = call("GetSnapshot")
                    if len(snapshot["devices"]) == 2 and all(device["online"] for device in snapshot["devices"]):
                        break
                except GLib.Error:
                    pass
                time.sleep(0.05)
            else:
                raise AssertionError("Demo service did not become ready")
            assert snapshot["demo"]
            signals = []
            bus.signal_subscribe(BUS_NAME, INTERFACE, "Changed", OBJECT_PATH, None,
                                 Gio.DBusSignalFlags.NONE,
                                 lambda *args: signals.append(args[5].unpack()[0]))
            snapshot = call("SetDevice", "(ss)", ("demo01", json.dumps({"power": False, "target_temperature": 22})))
            device = next(device for device in snapshot["devices"] if device["id"] == "demo01")
            assert device["state"]["power"] is False
            assert device["state"]["target_temperature"] == 22
            snapshot = call("RenameDevice", "(ss)", ("demo01", "Lounge"))
            assert any(device["name"] == "Lounge" for device in snapshot["devices"])
            try:
                call("SetDevice", "(ss)", ("demo01", '{"target_temperature":999}'))
            except GLib.Error as exc:
                assert "between" in str(exc)
            else:
                raise AssertionError("Service accepted an invalid temperature")
            try:
                call("SetDevice", "(ss)", ("demo01", "invalid-json"))
            except GLib.Error:
                pass
            else:
                raise AssertionError("Service accepted malformed settings")
            snapshot = call("Scan", "(s)", ("",))
            assert len(snapshot["devices"]) == 2
            context = GLib.MainContext.default()
            while context.pending():
                context.iteration(False)
            assert signals, "No change signals received"
            print("Private D-Bus integration passed")
        finally:
            process.terminate()
            output, error = process.communicate(timeout=10)
            if process.returncode != 0:
                raise AssertionError(f"Service shutdown failed ({process.returncode})\n{output}\n{error}")


if __name__ == "__main__":
    main()
