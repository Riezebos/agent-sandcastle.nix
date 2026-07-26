"""Building a MicroVM runner from a JSON sandbox specification.

The spec is copied into the Nix store first and the resulting store path is
what gets spliced into the evaluated expression. Nothing an operator typed
ever reaches Nix as source text, so a package name or sandbox name cannot
turn into Nix code.
"""

import ipaddress
import json
import os
import shutil
import subprocess
import tempfile

from . import state, validate
from .errors import BuildError, StateError

NIX_EXPERIMENTAL_FEATURES = "nix-command flakes"


def nix_binary():
    return os.environ.get("SANDCASTLE_NIX", "nix")


def nix_store_binary():
    return os.environ.get("SANDCASTLE_NIX_STORE", "nix-store")


def build_input(config, spec):
    """Return the document the Nix builder evaluates for `spec`.

    It is the specification plus the host network parameters the guest needs
    at build time. Those stay out of the persisted spec so changing the
    bridge subnet is a rebuild rather than a rewrite of every spec.
    """
    document = spec.to_dict()
    document["network"] = {
        "gateway": config.host_address,
        "prefixLength": ipaddress.IPv4Network(config.subnet, strict=True).prefixlen,
        "nameservers": list(config.nameservers),
    }
    return document


def add_build_input_to_store(config, spec):
    """Copy a build input into the Nix store and return its store path."""
    document = build_input(config, spec)
    with tempfile.TemporaryDirectory(prefix="sandcastle-spec-") as directory:
        path = os.path.join(directory, "sandbox-spec.json")
        with open(path, "w", encoding="utf-8") as handle:
            handle.write(json.dumps(document, indent=2, sort_keys=True) + "\n")
        result = _run(
            [nix_store_binary(), "--add", path],
            "copy the sandbox build input into the store",
        )
    return validate.validate_store_path(result.strip())


def build_runner(config, spec, extra_nix_args=()):
    """Build `spec`'s MicroVM runner and return its store path.

    The runner is realised but not installed; callers decide when to move
    `current`, so a failed build can never disturb a working sandbox.
    """
    if not config.flake_ref:
        raise StateError(
            "no flake reference configured; set flakeRef in the host config or "
            "pass --flake"
        )

    spec_path = add_build_input_to_store(config, spec)
    expression = (
        f'(builtins.getFlake "{_escape_nix_string(config.flake_ref)}")'
        f".lib.runnerFromSpecFile {spec_path}"
    )

    command = [
        nix_binary(),
        "--extra-experimental-features",
        NIX_EXPERIMENTAL_FEATURES,
        "build",
        # getFlake on a plain store path is an unlocked flake reference, and
        # readFile of a store path is an absolute path: both need impure
        # evaluation. The expression itself is fully generated from validated
        # values and a content-addressed store path.
        "--impure",
        "--no-link",
        "--print-out-paths",
        "--expr",
        expression,
        *extra_nix_args,
    ]
    output = _run(command, f"build the runner for sandbox {spec.name!r}")
    return validate.validate_store_path(output.strip().splitlines()[-1])


def install_runner(config, name, runner_path):
    """Point `<vms>/<name>/current` and the GC root at `runner_path`.

    The previous runner is retained as the `previous` GC root so a failed
    activation can be rolled back without rebuilding.
    """
    name = validate.validate_name(name)
    runner_path = validate.validate_store_path(runner_path)

    vm_dir = config.vm_dir(name)
    os.makedirs(vm_dir, mode=0o775, exist_ok=True)
    _chown_vm_path(config, vm_dir)

    previous = state.installed_runner(config, name)
    if previous is not None and previous != runner_path:
        state.install_gc_root(config, name, "previous", previous)

    state.install_gc_root(config, name, "current", runner_path)
    current = os.path.join(vm_dir, "current")
    state.atomic_symlink(current, runner_path)
    _chown_vm_path(config, current, follow_symlinks=False)
    return previous


def rollback_runner(config, name):
    """Restore the previous runner. Returns its path, or None if there is none."""
    previous = state.read_gc_root(config, name, "previous")
    if previous is None:
        return None
    install_runner(config, name, previous)
    return previous


def _chown_vm_path(config, path, follow_symlinks=True):
    """Give a state path to the microvm user, ignoring a non-root caller."""
    uid = _lookup_uid(config.vm_user)
    gid = _lookup_gid(config.vm_group)
    if uid is None or gid is None:
        return
    try:
        os.chown(path, uid, gid, follow_symlinks=follow_symlinks)
    except PermissionError:
        # Unit tests and dry runs operate on a state tree the caller owns.
        pass


def _lookup_uid(user):
    try:
        import pwd

        return pwd.getpwnam(user).pw_uid
    except (ImportError, KeyError):
        return None


def _lookup_gid(group):
    try:
        import grp

        return grp.getgrnam(group).gr_gid
    except (ImportError, KeyError):
        return None


def _escape_nix_string(value):
    """Escape a value for use inside a Nix double-quoted string."""
    return value.replace("\\", "\\\\").replace('"', '\\"').replace("${", "\\${")


def _run(command, what):
    if shutil.which(command[0]) is None and not os.path.isabs(command[0]):
        raise BuildError(f"cannot {what}: {command[0]} is not on PATH")
    try:
        completed = subprocess.run(
            command,
            check=False,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
    except OSError as error:
        raise BuildError(f"cannot {what}: {error}") from error

    if completed.returncode != 0:
        detail = completed.stderr.strip() or completed.stdout.strip()
        raise BuildError(f"failed to {what}:\n{detail}")
    return completed.stdout
