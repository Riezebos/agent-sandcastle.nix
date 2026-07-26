"""Host configuration the NixOS module hands to the CLI.

The host module writes `/etc/sandcastle/config.json` so the CLI never has to
guess the bridge subnet, the flake it should build sandboxes from, or where
state lives. Defaults here exist so the unit tests and `--config` overrides
can construct a Config without a deployed host.
"""

import ipaddress
import json
import os
from dataclasses import dataclass, field, replace

from .errors import StateError, ValidationError

DEFAULT_CONFIG_PATH = "/etc/sandcastle/config.json"

DEFAULT_STATE_DIR = "/var/lib/sandcastle"
DEFAULT_GC_ROOT_DIR = "/nix/var/nix/gcroots/sandcastle"


@dataclass(frozen=True)
class Config:
    """Resolved host settings for one sandcastle installation."""

    state_dir: str = DEFAULT_STATE_DIR
    gc_root_dir: str = DEFAULT_GC_ROOT_DIR
    flake_ref: str = ""
    bridge: str = "br-sandboxes"
    subnet: str = "10.88.0.0/24"
    host_address: str = "10.88.0.1"
    allocation_start: str = "10.88.0.16"
    allocation_end: str = "10.88.0.239"
    vsock_cid_start: int = 100
    vsock_cid_end: int = 65535
    route_zone: str = "example.com"
    max_running: int = 4
    vm_user: str = "microvm"
    vm_group: str = "kvm"
    nameservers: list = field(default_factory=lambda: ["10.88.0.1"])

    # Directories derived from `state_dir`. Kept as properties rather than
    # fields so a relocated state tree can never leave one of them behind.
    @property
    def specs_dir(self):
        return os.path.join(self.state_dir, "specs")

    @property
    def vms_dir(self):
        return os.path.join(self.state_dir, "vms")

    @property
    def credentials_dir(self):
        return os.path.join(self.state_dir, "credentials")

    @property
    def caddy_dir(self):
        return os.path.join(self.state_dir, "caddy")

    @property
    def locks_dir(self):
        return os.path.join(self.state_dir, "locks")

    @property
    def known_hosts_dir(self):
        return os.path.join(self.state_dir, "known-hosts")

    @property
    def network(self):
        return ipaddress.IPv4Network(self.subnet, strict=True)

    def spec_path(self, name):
        return os.path.join(self.specs_dir, f"{name}.json")

    def vm_dir(self, name):
        return os.path.join(self.vms_dir, name)

    def home_image_path(self, name):
        return os.path.join(self.vm_dir(name), "home.img")

    def gc_root_path(self, name, slot="current"):
        return os.path.join(self.gc_root_dir, f"{name}-{slot}")

    def allocation_range(self):
        """Yield every address the CLI is allowed to hand out, in order."""
        start = ipaddress.IPv4Address(self.allocation_start)
        end = ipaddress.IPv4Address(self.allocation_end)
        if end < start:
            raise ValidationError(
                f"allocation range {start}-{end} is inverted; check the host config"
            )
        network = self.network
        for value in range(int(start), int(end) + 1):
            address = ipaddress.IPv4Address(value)
            if address not in network:
                raise ValidationError(f"allocation address {address} is outside {network}")
            if address == ipaddress.IPv4Address(self.host_address):
                continue
            if address in (network.network_address, network.broadcast_address):
                continue
            yield str(address)

    def cid_range(self):
        if self.vsock_cid_end < self.vsock_cid_start:
            raise ValidationError("VSOCK CID range is inverted; check the host config")
        return range(self.vsock_cid_start, self.vsock_cid_end + 1)


# Keys accepted in config.json, mapped to their dataclass field names. An
# explicit map keeps an unexpected key an error rather than a silent no-op.
_KEYS = {
    "stateDir": "state_dir",
    "gcRootDir": "gc_root_dir",
    "flakeRef": "flake_ref",
    "bridge": "bridge",
    "subnet": "subnet",
    "hostAddress": "host_address",
    "allocationStart": "allocation_start",
    "allocationEnd": "allocation_end",
    "vsockCidStart": "vsock_cid_start",
    "vsockCidEnd": "vsock_cid_end",
    "routeZone": "route_zone",
    "maxRunning": "max_running",
    "vmUser": "vm_user",
    "vmGroup": "vm_group",
    "nameservers": "nameservers",
}


def from_dict(document):
    """Build a Config from a parsed config.json document."""
    if not isinstance(document, dict):
        raise StateError("host config must be a JSON object")
    unknown = sorted(set(document) - set(_KEYS))
    if unknown:
        raise StateError(f"unknown host config keys: {', '.join(unknown)}")
    overrides = {_KEYS[key]: value for key, value in document.items()}
    return replace(Config(), **overrides)


def load(path=None):
    """Load the host config, falling back to defaults when it is absent."""
    path = path or os.environ.get("SANDCASTLE_CONFIG") or DEFAULT_CONFIG_PATH
    try:
        with open(path, "r", encoding="utf-8") as handle:
            document = json.load(handle)
    except FileNotFoundError:
        if path != DEFAULT_CONFIG_PATH:
            raise StateError(f"host config {path} does not exist") from None
        return Config()
    except json.JSONDecodeError as error:
        raise StateError(f"host config {path} is not valid JSON: {error}") from error
    return from_dict(document)
