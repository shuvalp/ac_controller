import importlib.util
from pathlib import Path
import shutil
import subprocess
import sys
import unittest


class DBusTests(unittest.TestCase):
    @unittest.skipUnless(shutil.which("dbus-run-session") and importlib.util.find_spec("gi"),
                         "D-Bus and system PyGObject are required")
    def test_private_session_service(self):
        scenario = Path(__file__).with_name("dbus_scenario.py")
        result = subprocess.run(["dbus-run-session", "--", sys.executable, str(scenario)],
                                capture_output=True, text=True, timeout=30)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
