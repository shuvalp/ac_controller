"""Nonblocking desktop client for the session service."""

import json

import gi

gi.require_version("Gio", "2.0")
from gi.repository import Gio, GLib

from .model import BUS_NAME, INTERFACE, INTROSPECTION_XML, OBJECT_PATH


class Client:
    def __init__(self, on_snapshot, on_error):
        self.on_snapshot, self.on_error = on_snapshot, on_error
        self.snapshot = {"devices": [], "scanning": False, "error": "", "demo": False}
        self.connected = False
        self.proxy = None
        self.node = Gio.DBusNodeInfo.new_for_xml(INTROSPECTION_XML)
        Gio.DBusProxy.new_for_bus(
            Gio.BusType.SESSION, Gio.DBusProxyFlags.DO_NOT_AUTO_START,
            self.node.interfaces[0], BUS_NAME, OBJECT_PATH, INTERFACE, None, self._proxy_ready, None,
        )

    def _proxy_ready(self, source, result, data):
        try:
            self.proxy = Gio.DBusProxy.new_for_bus_finish(result)
            self.proxy.connect("g-signal", self._signal)
            self.proxy.connect("notify::g-name-owner", self._owner_changed)
            self._owner_changed()
        except GLib.Error as exc:
            self.on_error(str(exc))

    def _owner_changed(self, *_):
        self.connected = bool(self.proxy.get_name_owner())
        if self.connected:
            self.call("GetSnapshot")
        else:
            self.on_snapshot(self.snapshot)

    def _accept(self, raw):
        self.snapshot = json.loads(raw)
        self.connected = True
        self.on_snapshot(self.snapshot)

    def _signal(self, proxy, sender, signal, parameters):
        if signal == "Changed":
            self._accept(parameters.unpack()[0])

    def call(self, method, arguments=(), callback=None):
        if not self.proxy or not self.proxy.get_name_owner():
            self.on_error("Service is unavailable. Use Start service to reconnect.")
            if callback:
                callback(False)
            return
        signature = {"GetSnapshot": "()", "Scan": "(s)", "SetDevice": "(ss)", "RenameDevice": "(ss)"}[method]

        def finished(proxy, result, data):
            success = False
            try:
                self._accept(proxy.call_finish(result).unpack()[0])
                success = True
            except GLib.Error as exc:
                Gio.DBusError.strip_remote_error(exc)
                self.on_error(exc.message)
            finally:
                if callback:
                    callback(success)

        self.proxy.call(method, GLib.Variant(signature, arguments), Gio.DBusCallFlags.NONE,
                        60000, None, finished, None)
