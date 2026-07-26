"""On-disk state: locks, atomic writes, allocation, and GC roots.

Every mutation takes the global allocation lock, a per-sandbox lock, or
both, and every file lands through a same-directory temporary path plus
`os.replace` so a crash leaves either the old or the new content and never a
truncated file.
"""

import contextlib
import errno
import fcntl
import hashlib
import ipaddress
import os
import shutil
import tempfile

from . import spec as spec_module
from . import validate
from .errors import ConflictError, ExhaustedError, NotFoundError, StateError

DIRECTORY_MODE = 0o700
SPEC_MODE = 0o600

# `microvm@<name>.service` and `microvm-set-booted@<name>.service` run as the
# unprivileged microvm user with this directory as their working directory, and
# set-booted writes the `booted` symlink into it, so it cannot be root-only.
VM_DIRECTORY_MODE = 0o775

GLOBAL_LOCK = "global"

# Kernel interface names are capped at 15 characters, so guests name their TAP
# device from a hash of the sandbox name. Must stay in step with `tapPrefix`
# and `tapName` in nix/guest-module.nix.
TAP_PREFIX = "sc-"


def ensure_directories(config):
    """Create the state tree if it is missing. Idempotent."""
    os.makedirs(config.state_dir, mode=DIRECTORY_MODE, exist_ok=True)
    for path in (
        config.specs_dir,
        config.vms_dir,
        config.credentials_dir,
        config.locks_dir,
        config.known_hosts_dir,
        config.caddy_dir,
        config.ssh_dir,
    ):
        os.makedirs(path, mode=DIRECTORY_MODE, exist_ok=True)


def atomic_write_bytes(path, data, mode=SPEC_MODE):
    """Write `data` to `path`, replacing it atomically.

    The temporary file is created in the destination directory so the
    `os.replace` is a same-filesystem rename, and both the file and its
    directory are fsynced so the rename survives a crash.
    """
    directory = os.path.dirname(path) or "."
    handle, temporary = tempfile.mkstemp(dir=directory, prefix=".tmp-", suffix=".swap")
    try:
        with os.fdopen(handle, "wb") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        os.chmod(temporary, mode)
        os.replace(temporary, path)
    except BaseException:
        _unlink_quietly(temporary)
        raise
    _fsync_directory(directory)


def atomic_write_text(path, text, mode=SPEC_MODE):
    atomic_write_bytes(path, text.encode("utf-8"), mode=mode)


def atomic_symlink(path, target):
    """Point `path` at `target`, replacing any existing link atomically."""
    directory = os.path.dirname(path) or "."
    temporary = os.path.join(directory, f".tmp-{os.path.basename(path)}-{os.getpid()}")
    _unlink_quietly(temporary)
    try:
        os.symlink(target, temporary)
        os.replace(temporary, path)
    except BaseException:
        _unlink_quietly(temporary)
        raise
    _fsync_directory(directory)


@contextlib.contextmanager
def file_lock(config, name, blocking=True):
    """Hold an exclusive advisory lock for `name` under the locks directory.

    `name` is either `GLOBAL_LOCK` or a validated sandbox name, so the lock
    file path can never escape the locks directory.
    """
    if name != GLOBAL_LOCK:
        name = validate.validate_name(name)
    os.makedirs(config.locks_dir, mode=DIRECTORY_MODE, exist_ok=True)
    path = os.path.join(config.locks_dir, f"{name}.lock")

    descriptor = os.open(path, os.O_RDWR | os.O_CREAT | os.O_CLOEXEC, 0o600)
    try:
        flags = fcntl.LOCK_EX if blocking else fcntl.LOCK_EX | fcntl.LOCK_NB
        try:
            fcntl.flock(descriptor, flags)
        except OSError as error:
            if error.errno in (errno.EACCES, errno.EAGAIN):
                raise ConflictError(
                    f"another sandcastle operation is holding the {name} lock"
                ) from error
            raise
        yield path
    finally:
        os.close(descriptor)


@contextlib.contextmanager
def allocation_lock(config, blocking=True):
    """Serialise every allocation of names, addresses, and CIDs."""
    with file_lock(config, GLOBAL_LOCK, blocking=blocking) as path:
        yield path


class Store:
    """Reads and writes sandbox specs under the state tree."""

    def __init__(self, config):
        self.config = config

    def names(self):
        """Return the sorted names of every sandbox that has a spec."""
        try:
            entries = os.listdir(self.config.specs_dir)
        except FileNotFoundError:
            return []
        names = []
        for entry in entries:
            if not entry.endswith(".json") or entry.startswith("."):
                continue
            names.append(entry[: -len(".json")])
        return sorted(names)

    def exists(self, name):
        return os.path.exists(self.config.spec_path(validate.validate_name(name)))

    def load(self, name):
        name = validate.validate_name(name)
        path = self.config.spec_path(name)
        try:
            with open(path, "r", encoding="utf-8") as handle:
                text = handle.read()
        except FileNotFoundError:
            raise NotFoundError(f"sandbox {name!r} does not exist") from None
        loaded = spec_module.from_json(text, config=self.config)
        if loaded.name != name:
            raise StateError(f"{path} declares name {loaded.name!r} but is stored as {name!r}")
        return loaded

    def load_all(self):
        """Load every spec, skipping none: a corrupt spec is an error."""
        return [self.load(name) for name in self.names()]

    def save(self, spec):
        """Write a spec atomically. The caller must hold the sandbox lock."""
        os.makedirs(self.config.specs_dir, mode=DIRECTORY_MODE, exist_ok=True)
        atomic_write_text(self.config.spec_path(spec.name), spec.to_json(), mode=SPEC_MODE)

    def remove(self, name):
        name = validate.validate_name(name)
        try:
            os.unlink(self.config.spec_path(name))
        except FileNotFoundError:
            raise NotFoundError(f"sandbox {name!r} does not exist") from None
        _fsync_directory(self.config.specs_dir)


def tap_name(name):
    """Return the host TAP device a sandbox's runner creates."""
    name = validate.validate_name(name)
    return TAP_PREFIX + hashlib.sha256(name.encode("utf-8")).hexdigest()[:11]


def derive_mac(name, salt=0):
    """Derive a stable locally administered MAC address for `name`."""
    digest = hashlib.sha256(f"{name}\0{salt}".encode("utf-8")).hexdigest()
    octets = ["02"] + [digest[index : index + 2] for index in range(0, 10, 2)]
    return validate.validate_mac(":".join(octets))


def allocate(config, store, name, parent=None):
    """Reserve a name, IPv4 address, MAC, VSOCK CID, and machine identity.

    The caller must hold the allocation lock. Returns a Spec carrying only
    the allocated identity; resource sizes and packages are applied by the
    caller.
    """
    name = validate.validate_name(name)
    if store.exists(name):
        raise ConflictError(f"sandbox {name!r} already exists")

    existing = store.load_all()
    taken_ipv4 = {entry.ipv4 for entry in existing}
    taken_cids = {entry.vsock_cid for entry in existing}
    taken_macs = {entry.mac for entry in existing}

    ipv4 = _first_free(config.allocation_range(), taken_ipv4)
    if ipv4 is None:
        raise ExhaustedError(
            f"no free IPv4 address between {config.allocation_start} and {config.allocation_end}"
        )

    cid = _first_free(config.cid_range(), taken_cids)
    if cid is None:
        raise ExhaustedError(
            f"no free VSOCK CID between {config.vsock_cid_start} and {config.vsock_cid_end}"
        )

    mac = None
    for salt in range(256):
        candidate = derive_mac(name, salt)
        if candidate not in taken_macs:
            mac = candidate
            break
    if mac is None:
        raise ExhaustedError(f"could not derive a free MAC address for {name!r}")

    return spec_module.Spec(
        name=name,
        ipv4=validate.validate_ipv4(
            ipv4, subnet=config.subnet, forbidden=[config.host_address]
        ),
        mac=mac,
        vsock_cid=validate.validate_vsock_cid(cid),
        machine_id=spec_module.new_machine_id(),
        created_at=spec_module.now_iso(),
        parent=validate.validate_name(parent) if parent else "",
    )


def install_gc_root(config, name, slot, store_path):
    """Point a GC root at `store_path` so Nix cannot collect a live runner."""
    name = validate.validate_name(name)
    store_path = validate.validate_store_path(store_path)
    if slot not in ("current", "previous"):
        raise StateError(f"unknown GC root slot {slot!r}")
    os.makedirs(config.gc_root_dir, mode=0o755, exist_ok=True)
    path = config.gc_root_path(name, slot)
    atomic_symlink(path, store_path)
    return path


def read_gc_root(config, name, slot="current"):
    """Return the store path a GC root points at, or None."""
    try:
        return os.readlink(config.gc_root_path(validate.validate_name(name), slot))
    except (FileNotFoundError, OSError):
        return None


def remove_gc_root(config, name, slot="current"):
    _unlink_quietly(config.gc_root_path(validate.validate_name(name), slot))


def installed_runner(config, name):
    """Return the runner `<vms>/<name>/current` points at, or None."""
    try:
        return os.readlink(os.path.join(config.vm_dir(validate.validate_name(name)), "current"))
    except (FileNotFoundError, OSError):
        return None


def booted_runner(config, name):
    try:
        return os.readlink(os.path.join(config.vm_dir(validate.validate_name(name)), "booted"))
    except (FileNotFoundError, OSError):
        return None


def ensure_vm_dir(config, name):
    """Create a sandbox's VM directory and give it to the microvm user."""
    name = validate.validate_name(name)
    path = config.vm_dir(name)
    os.makedirs(path, exist_ok=True)
    # makedirs applies the caller's umask, and root's usual 022 would drop the
    # group write bit the set-booted unit needs.
    os.chmod(path, VM_DIRECTORY_MODE)
    chown_vm_path(config, path)
    return path


def remove_vm_dir(config, name):
    """Delete a sandbox's VM directory, disks and all."""
    return _remove_subdirectory(config.vms_dir, config.vm_dir(validate.validate_name(name)))


def remove_credentials(config, name, only_if_empty=False):
    """Delete a sandbox's credential directory.

    `only_if_empty` is what a failed `create` uses: reusing the name of a
    sandbox whose credentials a previous `delete` deliberately kept must not
    turn an unwind into silent data loss.
    """
    path = config.credentials_path(validate.validate_name(name))
    return _remove_subdirectory(config.credentials_dir, path, only_if_empty=only_if_empty)


def _remove_subdirectory(parent, path, only_if_empty=False):
    """Recursively delete `path`, which must be a real directory in `parent`.

    The path is always rebuilt from a validated name, and it is refused unless
    it really is a directory directly inside `parent`, so neither a tampered
    name nor a symlink planted in the state tree can turn a delete of sandbox
    state into a delete of something else.
    """
    if not os.path.exists(path):
        return False
    resolved = os.path.realpath(path)
    if os.path.dirname(resolved) != os.path.realpath(parent):
        raise StateError(f"{path} resolves to {resolved}, outside {parent}")
    if os.path.islink(path) or not os.path.isdir(path):
        raise StateError(f"{path} is not a directory")
    if only_if_empty and os.listdir(path):
        return False
    shutil.rmtree(path)
    _fsync_directory(parent)
    return True


def chown_vm_path(config, path, follow_symlinks=True):
    """Give a state path to the microvm user, ignoring a non-root caller."""
    uid = _lookup_uid(config.vm_user)
    gid = _lookup_gid(config.vm_group)
    if uid is None or gid is None:
        return
    try:
        os.chown(path, uid, gid, follow_symlinks=follow_symlinks)
    except (PermissionError, OSError):
        # Unit tests and dry runs operate on a state tree the caller owns.
        pass


def free_space_mib(path):
    """Return the free space in MiB on the filesystem holding `path`.

    Walks up to the nearest existing ancestor so this works before a
    sandbox's own directory has been created.
    """
    while not os.path.exists(path):
        parent = os.path.dirname(path)
        if parent == path:
            raise StateError(f"no existing ancestor of {path} to measure free space on")
        path = parent
    stats = os.statvfs(path)
    return (stats.f_bavail * stats.f_frsize) // (1024 * 1024)


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


def _first_free(candidates, taken):
    for candidate in candidates:
        if candidate not in taken:
            return candidate
    return None


def _fsync_directory(path):
    try:
        descriptor = os.open(path, os.O_RDONLY | os.O_DIRECTORY | os.O_CLOEXEC)
    except OSError:
        return
    try:
        os.fsync(descriptor)
    except OSError:
        # Some filesystems refuse directory fsync; the rename is still atomic.
        pass
    finally:
        os.close(descriptor)


def _unlink_quietly(path):
    try:
        os.unlink(path)
    except FileNotFoundError:
        pass


def address_in_subnet(config, address):
    """True when `address` belongs to the sandbox bridge subnet."""
    return ipaddress.IPv4Address(address) in config.network
