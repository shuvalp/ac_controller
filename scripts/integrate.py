"""Generate desktop integration with correctly quoted installation paths."""

import os
from pathlib import Path
import shlex
import sys


def quote_argument(value):
    # Both systemd and Desktop Entry Exec expand percent specifiers.
    return '"' + str(value).replace("\\", "\\\\").replace('"', '\\"').replace("%", "%%").replace("$", "$$") + '"'


def write(path, text, executable=False):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)
    path.chmod(0o755 if executable else 0o644)


def main():
    app_dir, templates = (Path(value).resolve() for value in sys.argv[1:])
    user_home = Path.home()
    config = Path(os.environ.get("XDG_CONFIG_HOME", user_home / ".config"))
    data = Path(os.environ.get("XDG_DATA_HOME", user_home / ".local/share"))
    python = app_dir / "venv/bin/python"
    launcher = user_home / ".local/bin/gree-ac"
    write(launcher, "#!/bin/sh\nexport GI_TYPELIB_PATH=" + shlex.quote(str(app_dir / "typelibs"))
          + '${GI_TYPELIB_PATH:+:$GI_TYPELIB_PATH}\nexec ' + shlex.quote(str(python))
          + ' -m gree_ac desktop "$@"\n', True)
    icon = app_dir / "gree-ac-symbolic.svg"
    from importlib.resources import files
    icon.write_bytes(files("gree_ac").joinpath("assets/gree-ac-symbolic.svg").read_bytes())
    replacements = {"@PYTHON@": quote_argument(python), "@LAUNCHER@": quote_argument(launcher),
                    "@ICON@": str(icon), "@TYPELIB_ENV@": quote_argument("GI_TYPELIB_PATH=" + str(app_dir / "typelibs"))}
    for name, destination in (
        ("gree-ac.service", config / "systemd/user/gree-ac.service"),
        ("gree-ac-indicator.service", config / "systemd/user/gree-ac-indicator.service"),
        ("gree-ac.desktop", data / "applications/gree-ac.desktop"),
    ):
        content = (templates / (name + ".in")).read_text()
        for placeholder, replacement in replacements.items():
            content = content.replace(placeholder, replacement)
        write(destination, content)


if __name__ == "__main__":
    main()
