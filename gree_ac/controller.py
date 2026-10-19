"""Async device lifecycle, discovery, command serialization, and reported state."""

import asyncio
from dataclasses import dataclass, field
from ipaddress import IPv4Address
import logging
import time

from greeclimate.discovery import Discovery, Listener

from .connection import DemoConnection, GreeConnection, close_protocol
from .model import clean_name, validate_settings

LOG = logging.getLogger(__name__)
INFO_FIELDS = ("ip", "port", "mac", "name", "brand", "model", "version", "mid")


@dataclass
class Record:
    info: dict
    alias: str = ""
    connection: object = None
    state: dict = field(default_factory=dict)
    online: bool = False
    pending: bool = False
    error: str = ""
    last_seen: float | None = None
    lock: asyncio.Lock = field(default_factory=asyncio.Lock)


class DiscoveryListener(Listener):
    def __init__(self, controller):
        self.controller = controller

    async def device_found(self, info):
        await self.controller.discovered({key: getattr(info, key) for key in INFO_FIELDS})

    async def device_update(self, info):
        await self.device_found(info)


class Controller:
    def __init__(self, store, *, demo=False, connection_factory=None, discovery_factory=Discovery):
        self.store = store
        self.demo = demo
        self.connection_factory = connection_factory or (DemoConnection if demo else GreeConnection)
        self.discovery_factory = discovery_factory
        self.records = {}
        for device_id, entry in store.data["devices"].items():
            self.records[device_id] = Record(info=entry["info"], alias=entry.get("alias", ""))
        self.on_change = lambda snapshot: None
        self.scanning = False
        self.error = ""
        self._scan_lock = asyncio.Lock()
        self._network_slots = asyncio.Semaphore(8)
        self._tasks = []

    def snapshot(self):
        return {
            "demo": self.demo, "scanning": self.scanning, "error": self.error,
            "devices": [
                {"id": device_id, "name": record.alias or record.info["name"],
                 "custom_name": record.alias,
                 "reported_name": record.info["name"], "ip": record.info["ip"],
                 "online": record.online, "pending": record.pending, "error": record.error,
                 "last_seen": record.last_seen, "state": dict(record.state)}
                for device_id, record in sorted(
                    self.records.items(), key=lambda item: (item[1].alias or item[1].info["name"]).casefold()
                )
            ],
        }

    def changed(self):
        self.on_change(self.snapshot())

    def persist(self):
        self.store.data["devices"] = {
            device_id: {"info": record.info, "alias": record.alias}
            for device_id, record in self.records.items()
        }
        self.store.save()

    async def start(self):
        self._tasks = [asyncio.create_task(self._scan_loop()), asyncio.create_task(self._poll_loop())]

    async def close(self):
        for task in self._tasks:
            task.cancel()
        await asyncio.gather(*self._tasks, return_exceptions=True)
        for record in self.records.values():
            if record.connection:
                record.connection.close()

    async def _scan_loop(self):
        while True:
            try:
                await self.scan()
            except Exception:
                LOG.exception("Discovery failed")
            await asyncio.sleep(60)

    async def _poll_loop(self):
        while True:
            await asyncio.sleep(10)
            await asyncio.gather(*(self.refresh(record) for record in list(self.records.values())))

    async def discovered(self, info):
        device_id = str(info["mac"]).replace(":", "").lower()
        info["name"] = clean_name(str(info["name"])) or device_id
        record = self.records.get(device_id)
        if record is None:
            record = self.records[device_id] = Record(info=info)
            self.persist()
        elif record.info != info:
            async with record.lock:
                if record.connection:
                    record.connection.close()
                record.connection = None
                record.info = info
                self.persist()
        self.changed()
        await self.refresh(record)

    async def scan(self, address=""):
        if not isinstance(address, str):
            raise ValueError("Supply an IPv4 address.")
        address = address.strip()
        if address:
            parsed = IPv4Address(address)
            if parsed.is_unspecified or parsed.is_multicast or str(parsed) == "255.255.255.255":
                raise ValueError("Supply a device's unicast IPv4 address.")
            address = str(parsed)
        async with self._scan_lock:
            self.scanning, self.error = True, ""
            self.changed()
            discovery = None
            try:
                if address and address not in self.store.data["manual_addresses"]:
                    self.store.data["manual_addresses"].append(address)
                    self.persist()
                if self.demo:
                    for suffix, name in (("01", "Living room"), ("02", "Bedroom")):
                        await self.discovered({
                            "ip": f"192.0.2.{int(suffix)}", "port": 7000,
                            "mac": f"demo{suffix}", "name": name,
                            "brand": "Demo", "model": None, "version": None, "mid": None,
                        })
                else:
                    discovery = self.discovery_factory()
                    discovery.add_listener(DiscoveryListener(self))
                    async with asyncio.timeout(40):
                        targets = [IPv4Address(address)] if address else [
                            IPv4Address(ip) for ip in self.store.data["manual_addresses"]
                        ]
                        if targets:
                            await discovery.scan(wait_for=3 if address else 0, target_addresses=targets)
                        if not address:
                            await discovery.scan(wait_for=3)
                    # Remembered ACs remain visible even when currently unreachable.
                    await asyncio.gather(*(
                        self.refresh(record) for record in list(self.records.values()) if not record.online
                    ))
            except Exception as exc:
                self.error = str(exc) or type(exc).__name__
                raise
            finally:
                if discovery:
                    close_protocol(discovery)
                self.scanning = False
                self.changed()
        return self.snapshot()

    async def _read(self, record):
        if record.connection is None:
            record.connection = self.connection_factory(record.info)
            await record.connection.connect()
        record.state = await record.connection.read()
        record.online, record.error, record.last_seen = True, "", time.time()

    def _failed(self, record, exc):
        record.online = False
        record.error = (str(exc) or type(exc).__name__) + ". Will retry automatically."
        if record.connection:
            record.connection.close()
        record.connection = None

    async def refresh(self, record):
        if record.lock.locked():
            return
        async with record.lock, self._network_slots:
            try:
                await self._read(record)
            except Exception as exc:
                self._failed(record, exc)
            self.changed()

    async def set_device(self, device_id, settings):
        record = self.records.get(device_id)
        if record is None:
            raise ValueError("Device was not found. Scan for devices first.")
        async with record.lock, self._network_slots:
            validate_settings(settings, record.state)
            if not record.online or record.connection is None:
                raise ValueError("Device is offline. Wait for reconnection or scan again.")
            record.pending, record.error = True, ""
            self.changed()
            try:
                await record.connection.write(settings)
                # Cache only data returned by the AC, never optimistic setter values.
                await self._read(record)
                mismatched = [key for key, value in settings.items() if record.state.get(key) != value]
                if mismatched:
                    record.error = "Device did not confirm: " + ", ".join(mismatched)
                    raise ValueError(record.error)
            except ValueError:
                raise
            except Exception as exc:
                self._failed(record, exc)
                raise ValueError("Could not confirm the change. " + record.error) from exc
            finally:
                record.pending = False
                self.changed()
        return self.snapshot()

    async def rename_device(self, device_id, name):
        if device_id not in self.records:
            raise ValueError("Device was not found.")
        self.records[device_id].alias = clean_name(name)
        self.persist()
        self.changed()
        return self.snapshot()
