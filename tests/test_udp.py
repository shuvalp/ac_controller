"""Exercise the real greeclimate adapter against an encrypted loopback peer."""

import asyncio
import json
import logging
import unittest

from greeclimate.cipher import CipherV1

from gree_ac.connection import GreeConnection

logging.getLogger().setLevel(logging.WARNING)


class SimulatedAC(asyncio.DatagramProtocol):
    def __init__(self):
        self.generic = CipherV1()
        self.private = CipherV1(b"0123456789abcdef")
        self.state = {"Pow": 1, "Mod": 1, "SetTem": 24, "TemUn": 0, "TemRec": 0,
                      "WdSpd": 0, "TemSen": 66, "SwingLfRig": 0, "SwUpDn": 1}
        self.commands = []
        self.omit = set()

    def connection_made(self, transport):
        self.transport = transport

    def datagram_received(self, packet, address):
        outer = json.loads(packet)
        cipher = self.generic if outer.get("i") == 1 else self.private
        message = cipher.decrypt(outer["pack"])
        if message["t"] == "bind":
            response = {"t": "bindok", "key": self.private.key}
        elif message["t"] == "status":
            cols = [key for key in message["cols"] if key in self.state and key not in self.omit]
            response = {"t": "dat", "cols": cols, "dat": [self.state[key] for key in cols]}
        elif message["t"] == "cmd":
            changes = dict(zip(message["opt"], message["p"]))
            self.commands.append(changes)
            self.state.update(changes)
            response = {"t": "res", "opt": list(changes), "val": list(changes.values())}
        else:
            return
        encrypted, _ = cipher.encrypt(response)
        self.transport.sendto(json.dumps({"t": "pack", "pack": encrypted}).encode(), address)


class UDPTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        loop = asyncio.get_running_loop()
        self.transport, self.ac = await loop.create_datagram_endpoint(
            SimulatedAC, local_addr=("127.0.0.1", 0))
        self.connection = GreeConnection({
            "ip": "127.0.0.1", "port": self.transport.get_extra_info("sockname")[1],
            "mac": "aabbccddee01", "name": "Loopback AC",
        })
        await self.connection.connect()

    async def asyncTearDown(self):
        self.connection.close()
        self.transport.close()
        await asyncio.sleep(0)

    async def test_bind_read_and_control_real_protocol(self):
        state = await self.connection.read()
        self.assertTrue(state["power"])
        self.assertEqual(state["current_temperature"], 26)
        await self.connection.write({"power": False, "target_temperature": 23})
        state = await self.connection.read()
        self.assertFalse(state["power"])
        self.assertEqual(state["target_temperature"], 23)
        self.assertEqual(self.ac.commands[-1]["SetTem"], 23)

    async def test_missing_response_field_cannot_confirm_setter_value(self):
        await self.connection.read()
        self.ac.omit.add("SwUpDn")
        await self.connection.write({"vertical_swing": 4})
        state = await self.connection.read()
        self.assertIsNone(state["vertical_swing"])

    async def test_units_are_applied_before_target(self):
        await self.connection.read()
        await self.connection.write({"target_temperature": 77, "temperature_units": 1})
        state = await self.connection.read()
        self.assertEqual(state["target_temperature"], 77)
        self.assertEqual(self.ac.commands[-1]["SetTem"], 25)
