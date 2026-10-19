import importlib.util
import os
from pathlib import Path
import shutil
import subprocess
import sys
import unittest


class GTKTests(unittest.TestCase):
    @unittest.skipUnless((os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY"))
                         and shutil.which("dbus-run-session") and importlib.util.find_spec("gi"),
                         "A graphical session and system PyGObject are required")
    def test_window_and_menu_with_demo_service(self):
        scenario = Path(__file__).with_name("gtk_scenario.py")
        env = dict(os.environ)
        # Editors packaged as snaps can export GTK modules incompatible with Ubuntu's GTK.
        for key in ("GTK_PATH", "GTK_MODULES", "GSETTINGS_SCHEMA_DIR"):
            env.pop(key, None)
        env["XDG_DATA_DIRS"] = "/usr/local/share:/usr/share"
        result = subprocess.run(["dbus-run-session", "--", sys.executable, str(scenario)],
                                capture_output=True, text=True, timeout=30, env=env)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertNotIn("Traceback", result.stderr)
