"""greeclimate adapter which waits for an actual status response."""

import asyncio

from greeclimate.device import Device
from greeclimate.deviceinfo import DeviceInfo

from .model import FIELDS


def close_protocol(protocol):
    # greeclimate.close() assumes a UDP transport was created, even after bind failures.
    try:
        protocol.close()
    except (AttributeError, RuntimeError):
        pass


class ObservedDevice(Device):
    def __init__(self, info):
        super().__init__(info, timeout=5, bind_timeout=3)
        # The library declares its handler table at class scope. Isolate devices.
        self._handlers = {}
        self.status_received = asyncio.Event()
        self.status_revision = 0
        self.reported_properties = {}

    def packet_received(self, obj, addr):
        super().packet_received(obj, addr)
        pack = obj.get("pack")
        if (isinstance(pack, dict) and str(pack.get("t", "")).lower() == "dat"
                and isinstance(pack.get("cols"), list) and isinstance(pack.get("dat"), list)):
            self.reported_properties = dict(zip(pack["cols"], pack["dat"]))
            self.status_revision += 1
            self.status_received.set()


class GreeConnection:
    def __init__(self, info):
        self.device = ObservedDevice(DeviceInfo(**info))

    async def connect(self):
        async with asyncio.timeout(10):
            await self.device.bind()

    async def read(self):
        revision = self.device.status_revision
        self.device.status_received.clear()
        await self.device.update_state()
        async with asyncio.timeout(6):
            while self.device.status_revision <= revision:
                await self.device.status_received.wait()
                self.device.status_received.clear()
        # Setters mutate the library's cache before any reply. Discard those
        # optimistic values, including fields omitted by unsupported devices.
        self.device.raw_properties.clear()
        self.device.raw_properties.update(self.device.reported_properties)
        return {key: getattr(self.device, key) for key in (*FIELDS, "current_temperature")}

    async def write(self, settings):
        # Units must be set before a target temperature, regardless of JSON key order.
        if "temperature_units" in settings:
            self.device.temperature_units = settings["temperature_units"]
        for key, value in settings.items():
            if key != "temperature_units":
                setattr(self.device, key, int(value) if key == "target_temperature" else value)
        await self.device.push_state_update()

    def close(self):
        close_protocol(self.device)


class DemoConnection:
    """Local simulation: no network traffic or real device changes."""

    def __init__(self, info):
        bedroom = info["mac"].endswith("02")
        self.state = {
            "power": not bedroom, "mode": 1, "target_temperature": 24,
            "temperature_units": 0, "fan_speed": 0, "current_temperature": 26 if not bedroom else 23,
            "horizontal_swing": 0, "vertical_swing": 1,
        }

    async def connect(self):
        await asyncio.sleep(0.05)

    async def read(self):
        await asyncio.sleep(0.05)
        return dict(self.state)

    async def write(self, settings):
        await asyncio.sleep(0.15)
        if "temperature_units" in settings and settings["temperature_units"] != self.state["temperature_units"]:
            to_f = settings["temperature_units"] == 1
            for key in ("current_temperature", "target_temperature"):
                value = self.state[key]
                self.state[key] = round(value * 9 / 5 + 32 if to_f else (value - 32) * 5 / 9)
        self.state.update(settings)

    def close(self):
        pass
