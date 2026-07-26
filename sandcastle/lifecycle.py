"""Create, start, stop, rebuild, and delete sandboxes.

Everything here is built on the conventions `microvm.nix` already provides:
the runner installed at `<stateDir>/<name>/current`, the generic
`microvm@<name>.service` template, and its companion TAP, virtiofsd, and
set-booted units. The CLI therefore never generates a unit; it only manages
state and calls systemctl.

Two rules shape the module:

- a build never disturbs a working sandbox. Runners are realised first and
  only then does `current` move, so a broken package list costs a failed
  build rather than a broken VM;
- a failed `create` leaves nothing addressable behind. The name is reserved
  first so two concurrent creates cannot collide, and everything reserved is
  released if a later step fails.
"""

import dataclasses
import os

from . import build, spec as spec_module, ssh, state, systemd, validate
from .errors import ConflictError, LifecycleError, StateError

# Headroom demanded on top of the declared disk sizes before a create is
# allowed. The store image, initrd, and kernel for one guest sit well inside
# this, and the images themselves are sparse.
CREATE_HEADROOM_MIB = 4096

# Free-space margin the identity volume needs. It only ever holds host keys.
IDENTITY_DISK_MIB = 32


def create(
    config,
    store,
    name,
    *,
    packages=(),
    agents=None,
    vcpu=None,
    memory_mib=None,
    home_disk_mib=None,
    parent=None,
    report=None,
):
    """Allocate, build, and install a new sandbox. Returns its spec.

    The VM is left stopped: the caller decides whether to start it.
    """
    report = report or (lambda _message: None)
    name = validate.validate_name(name)

    overrides = {"packages": spec_module.expand_packages(packages)}
    if agents is not None:
        overrides["agents"] = spec_module.validate_agents(agents)
    if vcpu is not None:
        overrides["vcpu"] = validate.validate_vcpu(vcpu)
    if memory_mib is not None:
        overrides["memory_mib"] = validate.validate_memory_mib(memory_mib)
    if home_disk_mib is not None:
        overrides["home_disk_mib"] = validate.validate_disk_mib(home_disk_mib)

    if parent is not None and not store.exists(parent):
        raise StateError(f"parent sandbox {parent!r} does not exist")

    # Reserving the name and its addresses under the global lock is what makes
    # two concurrent creates safe; the build that follows is slow and does not
    # need the lock.
    with state.allocation_lock(config):
        state.ensure_directories(config)
        allocated = dataclasses.replace(
            state.allocate(config, store, name, parent=parent), **overrides
        )
        _require_free_space(config, allocated)
        store.save(allocated)

    report(f"reserved {allocated.name}: {allocated.ipv4}, VSOCK CID {allocated.vsock_cid}")

    # A `delete` without --delete-credentials deliberately keeps this
    # directory, so whether it already existed decides whether an unwind may
    # remove it.
    credentials = config.credentials_path(allocated.name)
    credentials_existed = os.path.isdir(credentials)

    try:
        with state.file_lock(config, allocated.name):
            state.ensure_vm_dir(config, allocated.name)
            os.makedirs(credentials, mode=state.DIRECTORY_MODE, exist_ok=True)
            ssh.ensure_known_hosts(config, allocated.name)

            report(f"building the runner for {allocated.name}")
            runner = build.build_runner(config, allocated)
            build.install_runner(config, allocated.name, runner)
            report(f"installed {runner}")
    except BaseException:
        _unwind_create(config, store, allocated.name, keep_credentials=credentials_existed)
        raise

    return allocated


def start(config, store, name, *, wait=True, report=None):
    """Start a sandbox, refusing to exceed the host's concurrency limit."""
    report = report or (lambda _message: None)
    spec = store.load(name)
    _require_installed_runner(config, spec.name)

    running = sorted(systemd.running_names(store.names()))
    if spec.name in running:
        report(f"{spec.name} is already running")
        return spec

    if len(running) >= config.max_running:
        raise ConflictError(
            f"{len(running)} sandboxes are already running and this host allows "
            f"{config.max_running}: {', '.join(running)}"
        )

    _activate(spec.name, systemd.start, wait=wait, report=report)
    report(f"started {systemd.unit_name(spec.name)}")
    return spec


def stop(config, store, name, *, report=None):
    """Stop a sandbox through the runner's graceful shutdown."""
    report = report or (lambda _message: None)
    spec = store.load(name)
    systemd.stop(spec.name)
    report(f"stopped {systemd.unit_name(spec.name)}")
    return spec


def restart(config, store, name, *, wait=True, report=None):
    report = report or (lambda _message: None)
    spec = store.load(name)
    _require_installed_runner(config, spec.name)
    _activate(spec.name, systemd.restart, wait=wait, report=report)
    report(f"restarted {systemd.unit_name(spec.name)}")
    return spec


def rebuild(config, store, name, *, restart_guest=None, wait=True, report=None):
    """Build a candidate runner, then activate it, rolling back on failure.

    `restart_guest` defaults to "restart it if it was running": a rebuild of a
    stopped sandbox stays stopped, and a rebuild of a running one comes back
    on the new closure. Returns `(runner, changed)`.

    The candidate is realised before anything is touched, and `current` only
    moves once it exists, so a bad package list costs a failed build and not a
    broken sandbox. The old runner stays reachable as the `previous` GC root,
    which is what a rollback restores.
    """
    report = report or (lambda _message: None)
    spec = store.load(name)

    report(f"building a candidate runner for {spec.name}")
    candidate = build.build_runner(config, spec)

    with state.file_lock(config, spec.name):
        installed = state.installed_runner(config, spec.name)
        was_running = systemd.is_active(spec.name) == "active"
        should_restart = was_running if restart_guest is None else restart_guest

        if installed == candidate:
            report(f"{spec.name} already has {candidate} installed")
            if restart_guest:
                _activate(spec.name, systemd.restart, wait=wait, report=report)
                report(f"restarted {systemd.unit_name(spec.name)}")
            return candidate, False

        # `booted` still points at the old runner, so the unit's ExecStop keeps
        # shutting the running guest down with the runner it was started from.
        build.install_runner(config, spec.name, candidate)
        report(f"installed {candidate}")

        if not should_restart:
            if was_running:
                report(
                    f"{spec.name} keeps running its old closure until it is restarted"
                )
            return candidate, True

        try:
            _activate(spec.name, systemd.restart, wait=wait, report=report)
        except LifecycleError as failure:
            report(f"activation failed: {failure}")
            raise _roll_back(config, spec.name, candidate, wait, report, failure)

        report(f"restarted {systemd.unit_name(spec.name)} on the new runner")
        return candidate, True


def _roll_back(config, name, candidate, wait, report, failure):
    """Restore the previous runner. Returns the error the caller should raise."""
    restored = build.rollback_runner(config, name)
    if restored is None:
        return LifecycleError(
            f"{name} failed to activate {candidate} and has no previous runner to "
            f"roll back to; it is left stopped. See: sandcastle logs {name}"
        )

    report(f"rolled back to {restored}")
    try:
        _activate(name, systemd.restart, wait=wait, report=report)
    except LifecycleError:
        return LifecycleError(
            f"{name} failed to activate {candidate} and also failed to come back on "
            f"the rolled-back runner {restored}. See: sandcastle logs {name}"
        )
    return LifecycleError(
        f"{name} failed to activate {candidate}: {failure}. Rolled back to "
        f"{restored} and restarted it."
    )


def _activate(name, action, *, wait, report):
    """Run a systemctl verb and confirm the sandbox stayed up."""
    action(name)
    if not wait:
        report(f"not waiting for {name} to settle")
        return
    systemd.confirm_running(name)


def _require_installed_runner(config, name):
    if state.installed_runner(config, name) is None:
        raise StateError(
            f"sandbox {name!r} has no installed runner; run: sandcastle rebuild {name}"
        )


def delete(config, store, name, *, delete_credentials=False, report=None):
    """Remove a stopped sandbox. Credentials survive unless asked for.

    Returns the list of things that were removed, so the caller can tell the
    operator exactly what is gone and what remains.
    """
    report = report or (lambda _message: None)
    spec = store.load(name)

    if systemd.is_active(spec.name) == "active":
        raise ConflictError(
            f"sandbox {spec.name!r} is running; stop it first: sandcastle stop {spec.name}"
        )

    routes = _route_files(config, spec.name)
    if routes:
        raise ConflictError(
            f"sandbox {spec.name!r} still has web routes; remove them first: "
            + ", ".join(os.path.basename(route) for route in routes)
        )

    removed = []
    with state.file_lock(config, spec.name):
        if state.remove_vm_dir(config, spec.name):
            removed.append(config.vm_dir(spec.name))
        for slot in ("current", "previous"):
            if state.read_gc_root(config, spec.name, slot) is not None:
                state.remove_gc_root(config, spec.name, slot)
                removed.append(config.gc_root_path(spec.name, slot))
        if ssh.forget_known_hosts(config, spec.name):
            removed.append(config.known_hosts_path(spec.name))

        credentials = config.credentials_path(spec.name)
        if delete_credentials and os.path.isdir(credentials):
            state.remove_credentials(config, spec.name)
            removed.append(credentials)

        store.remove(spec.name)
        removed.append(config.spec_path(spec.name))

    for path in removed:
        report(f"removed {path}")
    if not delete_credentials and os.path.isdir(config.credentials_path(spec.name)):
        report(f"kept credentials in {config.credentials_path(spec.name)}")
    return removed


def status(config, store, name):
    """Return a flat status mapping for one sandbox, without evaluating Nix."""
    spec = store.load(name)
    installed = state.installed_runner(config, spec.name)
    booted = state.booted_runner(config, spec.name)
    properties = systemd.properties(
        spec.name, ("ActiveState", "SubState", "Result", "ExecMainStartTimestamp")
    )

    document = spec.to_dict()
    document.update(
        {
            "state": properties.get("ActiveState", systemd.UNKNOWN),
            "subState": properties.get("SubState", ""),
            "result": properties.get("Result", ""),
            "startedAt": properties.get("ExecMainStartTimestamp", ""),
            "unit": systemd.unit_name(spec.name),
            "runner": installed or "(not installed)",
            "bootedRunner": booted or "(not booted)",
            "stale": bool(booted and installed and booted != installed),
            "homeImage": config.home_image_path(spec.name),
            "homeImageMiB": _file_size_mib(config.home_image_path(spec.name)),
            "identityImage": config.identity_image_path(spec.name),
            "credentials": config.credentials_path(spec.name),
            "knownHosts": config.known_hosts_path(spec.name),
            "tapDevice": state.tap_name(spec.name),
            "sshDestination": ssh.destination(spec),
        }
    )
    return document


def _require_free_space(config, spec):
    needed = spec.home_disk_mib + IDENTITY_DISK_MIB + CREATE_HEADROOM_MIB
    available = state.free_space_mib(config.vms_dir)
    if available < needed:
        raise StateError(
            f"creating {spec.name!r} wants about {needed} MiB free under "
            f"{config.vms_dir} but only {available} MiB is available"
        )


def _route_files(config, name):
    """Return the Caddy snippets belonging to a sandbox, if any exist yet.

    Route management is M5's; this only has to recognise a snippet so that
    deleting a sandbox cannot leave a route pointing at a freed address, which
    the next `create` would then hand to a different sandbox. The snippets are
    generated by sandcastle, so the ownership marker is a fixed comment.
    """
    try:
        entries = sorted(os.listdir(config.caddy_dir))
    except FileNotFoundError:
        return []
    marker = f"# sandcastle-sandbox: {name}\n"
    routes = []
    for entry in entries:
        if not entry.endswith(".caddy"):
            continue
        path = os.path.join(config.caddy_dir, entry)
        try:
            with open(path, "r", encoding="utf-8") as handle:
                content = handle.read()
        except OSError:
            continue
        if marker in content:
            routes.append(path)
    return routes


def _unwind_create(config, store, name, *, keep_credentials):
    """Release everything a failed create reserved, best effort.

    Called from an exception handler, so a secondary failure here must not
    mask the original one.
    """
    steps = [
        lambda: state.remove_vm_dir(config, name),
        lambda: state.remove_gc_root(config, name, "current"),
        lambda: state.remove_gc_root(config, name, "previous"),
        lambda: ssh.forget_known_hosts(config, name),
    ]
    if not keep_credentials:
        steps.append(lambda: state.remove_credentials(config, name, only_if_empty=True))
    steps.append(lambda: store.remove(name))

    for step in steps:
        try:
            step()
        except Exception:  # noqa: BLE001 - unwinding must not raise
            pass


def _file_size_mib(path):
    try:
        return os.stat(path).st_size // (1024 * 1024)
    except OSError:
        return 0
