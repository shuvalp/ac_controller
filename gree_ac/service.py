"""Session D-Bus service; GTK's main loop and asyncio use separate threads."""

import asyncio
import concurrent.futures
import json
import logging
import signal
import threading

import gi

gi.require_version("Gio", "2.0")
from gi.repository import Gio, GLib

from .controller import Controller
from .model import BUS_NAME, INTERFACE, INTROSPECTION_XML, OBJECT_PATH
from .storage import Store

LOG = logging.getLogger(__name__)


class Worker:
    def __init__(self, config, demo, on_change):
        self.config, self.demo, self.on_change = config, demo, on_change
        self.ready = concurrent.futures.Future()
        self.thread = threading.Thread(target=self.run, name="gree-network", daemon=True)

    def run(self):
        try:
            asyncio.run(self.serve())
        except Exception as exc:
            if not self.ready.done():
                self.ready.set_exception(exc)
            LOG.exception("Network worker stopped")

    async def serve(self):
        self.loop = asyncio.get_running_loop()
        self.stop_event = asyncio.Event()
        self.controller = Controller(Store(self.config), demo=self.demo)
        self.controller.on_change = self.on_change
        await self.controller.start()
        self.ready.set_result(True)
        try:
            await self.stop_event.wait()
        finally:
            tasks = [task for task in asyncio.all_tasks() if task is not asyncio.current_task()]
            for task in tasks:
                task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)
            await self.controller.close()

    async def dispatch(self, method, parameters):
        if method == "GetSnapshot":
            return self.controller.snapshot()
        if method == "Scan":
            return await self.controller.scan(*parameters)
        if method == "SetDevice":
            device_id, raw_settings = parameters
            return await self.controller.set_device(device_id, json.loads(raw_settings))
        if method == "RenameDevice":
            return await self.controller.rename_device(*parameters)
        raise ValueError("Unknown method")

    def stop(self):
        if self.thread.is_alive() and hasattr(self, "stop_event"):
            self.loop.call_soon_threadsafe(self.stop_event.set)
            self.thread.join(timeout=10)


def main(config=None, demo=False):
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s", force=True)
    # greeclimate logs the negotiated binding key at INFO; do not put it in the journal.
    logging.getLogger("greeclimate").setLevel(logging.WARNING)
    connection = Gio.bus_get_sync(Gio.BusType.SESSION, None)
    result = connection.call_sync(
        "org.freedesktop.DBus", "/org/freedesktop/DBus", "org.freedesktop.DBus", "RequestName",
        GLib.Variant("(su)", (BUS_NAME, 4)), GLib.VariantType.new("(u)"),
        Gio.DBusCallFlags.NONE, 5000, None,
    )
    if result.unpack()[0] != 1:
        raise RuntimeError("AC Controller service is already running in this login session.")
    main_loop = GLib.MainLoop()

    def emit(snapshot):
        if not connection.is_closed():
            connection.emit_signal(None, OBJECT_PATH, INTERFACE, "Changed",
                                   GLib.Variant("(s)", (json.dumps(snapshot),)))
        return GLib.SOURCE_REMOVE

    worker = Worker(config, demo, lambda snapshot: GLib.idle_add(emit, snapshot))

    def reply(invocation, future):
        try:
            snapshot = future.result()
            invocation.return_value(GLib.Variant("(s)", (json.dumps(snapshot),)))
        except ValueError as exc:
            invocation.return_dbus_error(INTERFACE + ".InvalidArgument", str(exc))
        except Exception as exc:
            LOG.exception("Request failed")
            invocation.return_dbus_error(INTERFACE + ".Failed", str(exc) or type(exc).__name__)
        return GLib.SOURCE_REMOVE

    def method_call(bus, sender, path, interface, method, parameters, invocation):
        future = asyncio.run_coroutine_threadsafe(worker.dispatch(method, parameters.unpack()), worker.loop)
        future.add_done_callback(lambda completed: GLib.idle_add(reply, invocation, completed))

    node = Gio.DBusNodeInfo.new_for_xml(INTROSPECTION_XML)
    registration = connection.register_object(OBJECT_PATH, node.interfaces[0], method_call, None, None)
    worker.thread.start()
    worker.ready.result(timeout=10)

    def stop():
        main_loop.quit()
        return GLib.SOURCE_REMOVE

    GLib.unix_signal_add(GLib.PRIORITY_DEFAULT, signal.SIGTERM, stop)
    GLib.unix_signal_add(GLib.PRIORITY_DEFAULT, signal.SIGINT, stop)
    connection.connect("closed", lambda *_: main_loop.quit())
    LOG.info("AC Controller service ready%s", " (simulation)" if demo else "")
    try:
        main_loop.run()
    finally:
        connection.unregister_object(registration)
        worker.stop()
