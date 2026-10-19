import asyncio
import copy
import os
from pathlib import Path
import tempfile
import unittest

from gree_ac.connection import DemoConnection
from gree_ac.controller import Controller
from gree_ac.model import validate_settings
from gree_ac.storage import Store

INFO = {"ip": "192.0.2.1", "port": 7000, "mac": "aa:bb:cc:dd:ee:01",
        "name": "Living room", "brand": None, "model": None, "version": None, "mid": None}


class FakeConnection(DemoConnection):
    def __init__(self, info):
        super().__init__(info)
        self.fail_read = False
        self.reject = False
        self.active_writes = 0
        self.max_active_writes = 0
        self.writes = []
        self.closed = False

    async def read(self):
        if self.fail_read:
            raise TimeoutError("No reply")
        return await super().read()

    async def write(self, settings):
        self.active_writes += 1
        self.max_active_writes = max(self.max_active_writes, self.active_writes)
        self.writes.append(dict(settings))
        await asyncio.sleep(0.01)
        if not self.reject:
            self.state.update(settings)
        self.active_writes -= 1

    def close(self):
        self.closed = True


class ControllerTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.store = Store(Path(self.temp.name) / "config/devices.json")
        self.connections = []

        def factory(info):
            connection = FakeConnection(info)
            self.connections.append(connection)
            return connection

        self.controller = Controller(self.store, connection_factory=factory)
        self.notifications = []
        self.controller.on_change = lambda snapshot: self.notifications.append(copy.deepcopy(snapshot))
        await self.controller.discovered(dict(INFO))
        self.device_id = "aabbccddee01"
        self.record = self.controller.records[self.device_id]

    async def asyncTearDown(self):
        await self.controller.close()
        self.temp.cleanup()

    async def test_discovery_reads_without_changing_settings(self):
        self.assertTrue(self.record.online)
        self.assertEqual(self.record.state["target_temperature"], 24)
        self.assertEqual(self.connections[0].writes, [])

    async def test_command_confirms_reported_state(self):
        result = await self.controller.set_device(self.device_id, {"power": False, "target_temperature": 23})
        self.assertFalse(result["devices"][0]["state"]["power"])
        self.assertEqual(result["devices"][0]["state"]["target_temperature"], 23)
        pending = [entry["devices"][0] for entry in self.notifications if entry["devices"][0]["pending"]]
        self.assertTrue(pending)
        self.assertEqual(pending[0]["state"]["target_temperature"], 24)
        self.assertFalse(self.record.pending)

    async def test_unconfirmed_command_reports_actual_state(self):
        self.connections[0].reject = True
        with self.assertRaisesRegex(ValueError, "did not confirm"):
            await self.controller.set_device(self.device_id, {"target_temperature": 22})
        self.assertEqual(self.record.state["target_temperature"], 24)
        self.assertTrue(self.record.online)
        self.assertFalse(self.record.pending)

    async def test_timeout_never_reports_optimistic_state(self):
        self.connections[0].fail_read = True
        with self.assertRaisesRegex(ValueError, "Could not confirm"):
            await self.controller.set_device(self.device_id, {"target_temperature": 22})
        self.assertEqual(self.record.state["target_temperature"], 24)
        self.assertFalse(self.record.online)
        self.assertFalse(self.record.pending)
        self.assertTrue(self.connections[0].closed)

    async def test_offline_reconnects(self):
        self.connections[0].fail_read = True
        await self.controller.refresh(self.record)
        self.assertFalse(self.record.online)
        with self.assertRaisesRegex(ValueError, "offline"):
            await self.controller.set_device(self.device_id, {"power": True})
        await self.controller.refresh(self.record)
        self.assertTrue(self.record.online)
        self.assertEqual(len(self.connections), 2)

    async def test_commands_are_serialized_per_device(self):
        await asyncio.gather(
            self.controller.set_device(self.device_id, {"target_temperature": 22}),
            self.controller.set_device(self.device_id, {"target_temperature": 23}),
        )
        self.assertEqual(self.connections[0].max_active_writes, 1)
        self.assertEqual(self.record.state["target_temperature"], 23)

    async def test_ip_changes_preserve_identity_and_alias(self):
        await self.controller.rename_device(self.device_id, "Lounge")
        await self.controller.discovered({**INFO, "ip": "192.0.2.42"})
        self.assertEqual(len(self.controller.records), 1)
        self.assertEqual(self.record.alias, "Lounge")
        self.assertEqual(self.record.info["ip"], "192.0.2.42")
        self.assertTrue(self.connections[0].closed)

    async def test_names_and_known_devices_survive_restart(self):
        await self.controller.rename_device(self.device_id, "  Lounge   AC ")
        other = Controller(Store(self.store.path))
        self.assertEqual(other.snapshot()["devices"][0]["name"], "Lounge AC")
        self.assertFalse(other.snapshot()["devices"][0]["online"])
        self.assertEqual(os.stat(self.store.path).st_mode & 0o777, 0o600)

    async def test_invalid_settings_never_reach_device(self):
        for settings in ({"power": 1}, {"mode": True}, {"fan_speed": 99},
                         {"target_temperature": 100}, {"target_temperature": 22.5},
                         {"target_temperature": float("nan")}, {"ip": "1.2.3.4"}, []):
            with self.subTest(settings=settings), self.assertRaises(ValueError):
                await self.controller.set_device(self.device_id, settings)
        self.assertEqual(self.connections[0].writes, [])

    async def test_scan_errors_reset_busy_state(self):
        def broken_discovery():
            raise OSError("Network unavailable")
        self.controller.discovery_factory = broken_discovery
        with self.assertRaisesRegex(OSError, "Network unavailable"):
            await self.controller.scan()
        self.assertFalse(self.controller.scanning)
        self.assertIn("Network unavailable", self.controller.error)

    async def test_manual_ip_is_validated_before_scanning(self):
        for address in ("not-an-ip", "::1", "0.0.0.0", "224.0.0.1"):
            with self.subTest(address=address), self.assertRaises(ValueError):
                await self.controller.scan(address)

    async def test_demo_never_uses_network_discovery(self):
        def unexpected_network():
            raise AssertionError("Demo attempted network discovery")
        demo = Controller(Store(Path(self.temp.name) / "demo.json"), demo=True,
                          discovery_factory=unexpected_network)
        result = await demo.scan()
        self.assertTrue(result["demo"])
        self.assertEqual(len(result["devices"]), 2)
        self.assertTrue(all(device["online"] for device in result["devices"]))
        await demo.set_device("demo01", {"temperature_units": 1})
        self.assertEqual(demo.records["demo01"].state["target_temperature"], 75)
        await demo.close()


class ValidationTests(unittest.TestCase):
    def test_temperature_units_and_ranges(self):
        validate_settings({"temperature_units": 1, "target_temperature": 77}, {"temperature_units": 0})
        with self.assertRaises(ValueError):
            validate_settings({"target_temperature": 77}, {"temperature_units": 0})
        with self.assertRaises(ValueError):
            validate_settings({"target_temperature": 24}, {})

    def test_unreported_swing_is_disabled(self):
        with self.assertRaisesRegex(ValueError, "support"):
            validate_settings({"vertical_swing": 1}, {})

    def test_bad_config_is_preserved(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "devices.json"
            path.write_text("broken config")
            with self.assertRaisesRegex(ValueError, "Cannot read"):
                Store(path)
            self.assertEqual(path.read_text(), "broken config")
