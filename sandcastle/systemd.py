"""The systemd interaction the CLI needs.

Unit names are always built from an already validated sandbox name, so the
instance part cannot contain a separator or escape into another unit. Every
call is an argument vector: nothing is handed to a shell.

`microvm.nix` provides the generic `microvm@<name>.service` template plus the
companion TAP, virtiofsd, and set-booted units, so the CLI never generates a
unit of its own.
"""

import os
import shutil
import subprocess
import time

from . import validate
from .errors import LifecycleError

UNIT_TEMPLATE = "microvm@{name}.service"

# The units that together make up one running sandbox. `logs` reads all of
# them because a failure to start is usually reported by a companion unit
# rather than by the hypervisor itself.
COMPANION_TEMPLATES = (
    "microvm-tap-interfaces@{name}.service",
    "microvm-virtiofsd@{name}.service",
    "microvm-set-booted@{name}.service",
)

UNKNOWN = "unknown"

# How long a freshly started sandbox must stay up before the CLI calls the
# activation a success, and how long it is willing to wait for that.
DEFAULT_SETTLE_SECONDS = 5.0
DEFAULT_TIMEOUT_SECONDS = 30.0
POLL_INTERVAL_SECONDS = 0.5

READINESS_PROPERTIES = ("ActiveState", "SubState", "InvocationID", "Result")


def unit_name(name):
    return UNIT_TEMPLATE.format(name=validate.validate_name(name))


def unit_names(name):
    """Return the hypervisor unit followed by its companion units."""
    name = validate.validate_name(name)
    return [unit_name(name)] + [
        template.format(name=name) for template in COMPANION_TEMPLATES
    ]


def systemctl_binary():
    return os.environ.get("SANDCASTLE_SYSTEMCTL", "systemctl")


def journalctl_binary():
    return os.environ.get("SANDCASTLE_JOURNALCTL", "journalctl")


def available():
    """True when systemd is reachable, so `list` can degrade instead of fail."""
    return shutil.which(systemctl_binary()) is not None


def is_active(name):
    """Return the systemd active state for a sandbox, or 'unknown'."""
    return active_states([name]).get(validate.validate_name(name), UNKNOWN)


def active_states(names):
    """Return `{name: state}` for many sandboxes using one systemctl call.

    `systemctl is-active` prints one line per unit in the order it was asked,
    which is what keeps `list` and `status` free of per-sandbox subprocesses
    and free of any Nix evaluation.
    """
    names = [validate.validate_name(name) for name in names]
    if not names:
        return {}
    if not available():
        return {name: UNKNOWN for name in names}

    completed = _run([systemctl_binary(), "is-active", *(unit_name(n) for n in names)])
    if completed is None:
        return {name: UNKNOWN for name in names}

    # A non-zero exit only means "not all active"; the output is still valid.
    lines = completed.stdout.splitlines()
    states = {}
    for index, name in enumerate(names):
        states[name] = lines[index].strip() if index < len(lines) else UNKNOWN
    return states


def running_names(names):
    """Return the subset of `names` whose hypervisor unit is active."""
    return {name for name, state in active_states(names).items() if state == "active"}


def properties(name, keys):
    """Return the requested `systemctl show` properties for one sandbox."""
    keys = list(keys)
    if not available():
        return {}
    completed = _run(
        [
            systemctl_binary(),
            "show",
            unit_name(name),
            *(f"--property={key}" for key in keys),
        ]
    )
    if completed is None:
        return {}

    values = {}
    for line in completed.stdout.splitlines():
        key, separator, value = line.partition("=")
        if separator:
            values[key] = value
    return values


def start(name):
    _act("start", name)


def stop(name):
    _act("stop", name)


def restart(name):
    _act("restart", name)


def confirm_running(
    name,
    *,
    settle=DEFAULT_SETTLE_SECONDS,
    timeout=DEFAULT_TIMEOUT_SECONDS,
    sleep=time.sleep,
    clock=time.monotonic,
):
    """Wait until a sandbox has stayed up long enough to count as activated.

    For qemu, `microvm@<name>.service` is `Type=simple`: `systemctl start`
    returns as soon as the hypervisor is forked, and `Restart=always` then
    turns a guest that cannot boot into a silent restart loop rather than a
    reported failure. Activation is therefore confirmed by watching the unit
    hold one invocation in a running state, which is what makes the rollback
    after a bad rebuild trigger at all.

    The unit's invocation ID identifies one start attempt, so a change in it
    means the hypervisor died and systemd restarted it.
    """
    if not available():
        return {}

    deadline = clock() + max(timeout, settle)
    invocation = None
    stable_since = None

    while True:
        latest = properties(name, READINESS_PROPERTIES)
        active = latest.get("ActiveState", UNKNOWN)
        sub = latest.get("SubState", "")
        current = latest.get("InvocationID", "")

        if active == "failed":
            result = latest.get("Result", "")
            raise LifecycleError(
                f"{unit_name(name)} failed"
                + (f" ({result})" if result else "")
                + f"; see: sandcastle logs {name}"
            )
        if sub == "auto-restart" or (invocation and current and current != invocation):
            raise LifecycleError(
                f"{unit_name(name)} died and was restarted immediately after "
                f"activation; the guest is not booting. See: sandcastle logs {name}"
            )

        now = clock()
        if active == "active" and sub == "running":
            if invocation is None:
                invocation = current
            if stable_since is None:
                stable_since = now
            if now - stable_since >= settle:
                return latest
        else:
            stable_since = None

        if now >= deadline:
            raise LifecycleError(
                f"{unit_name(name)} did not hold a running state for {settle:.0f}s "
                f"within {timeout:.0f}s (state {active}/{sub}); "
                f"see: sandcastle logs {name}"
            )
        sleep(POLL_INTERVAL_SECONDS)


def journal_command(name, *, lines=None, follow=False):
    """Return the argv that reads a sandbox's host-side journal."""
    command = [journalctl_binary()]
    for unit in unit_names(name):
        command += ["--unit", unit]
    if lines is not None:
        command += ["--lines", str(validate.validate_line_count(lines))]
    if follow:
        command.append("--follow")
    return command


def _act(verb, name):
    unit = unit_name(name)
    if not available():
        raise LifecycleError(
            f"cannot {verb} {unit}: {systemctl_binary()} is not on PATH; "
            "sandcastle expects to run on the sandbox host"
        )
    completed = _run([systemctl_binary(), verb, unit])
    if completed is None or completed.returncode != 0:
        detail = ""
        if completed is not None:
            detail = (completed.stderr.strip() or completed.stdout.strip()).strip()
        raise LifecycleError(
            f"systemctl {verb} {unit} failed"
            + (f": {detail}" if detail else "")
            + f"; see: sandcastle logs {name}"
        )


def _run(command):
    try:
        return subprocess.run(
            command,
            check=False,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
    except OSError:
        return None
