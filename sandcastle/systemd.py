"""The small amount of systemd interaction the CLI needs.

Unit names are always built from an already validated sandbox name, so the
instance part cannot contain a separator or escape into another unit.
"""

import os
import shutil
import subprocess

from . import validate

UNIT_TEMPLATE = "microvm@{name}.service"


def unit_name(name):
    return UNIT_TEMPLATE.format(name=validate.validate_name(name))


def systemctl_binary():
    return os.environ.get("SANDCASTLE_SYSTEMCTL", "systemctl")


def is_active(name):
    """Return the systemd active state for a sandbox, or 'unknown'."""
    binary = systemctl_binary()
    if shutil.which(binary) is None:
        return "unknown"
    try:
        completed = subprocess.run(
            [binary, "is-active", unit_name(name)],
            check=False,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
        )
    except OSError:
        return "unknown"
    return completed.stdout.strip() or "unknown"
