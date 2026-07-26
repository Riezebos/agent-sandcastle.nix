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
import tempfile

from . import spec as spec_module
from . import validate
from .errors import ConflictError, ExhaustedError, NotFoundError, StateError

DIRECTORY_MODE = 0o700
SPEC_MODE = 0o600

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
