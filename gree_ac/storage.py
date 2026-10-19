"""Atomic, private storage for device identities and friendly names."""

import json
import os
from pathlib import Path
import tempfile


def default_config_path():
    return Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config")) / "gree-ac" / "devices.json"


class Store:
    def __init__(self, path=None):
        self.path = Path(path) if path else default_config_path()
        self.data = {"version": 1, "devices": {}, "manual_addresses": []}
        if self.path.exists():
            try:
                data = json.loads(self.path.read_text())
                if (data.get("version") != 1 or not isinstance(data.get("devices"), dict)
                        or not isinstance(data.get("manual_addresses"), list)):
                    raise ValueError("Unsupported configuration format")
                self.data = data
            except (ValueError, AttributeError) as exc:
                raise ValueError(f"Cannot read {self.path}: {exc}. Repair it or move it aside.") from exc

    def save(self):
        self.path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        descriptor, temporary = tempfile.mkstemp(prefix=".devices-", dir=self.path.parent)
        try:
            with os.fdopen(descriptor, "w") as stream:
                json.dump(self.data, stream, indent=2)
                stream.write("\n")
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, self.path)
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)
