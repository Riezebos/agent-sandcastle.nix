"""Strict validation of every operator-supplied value.

These functions are pure and do no I/O so they can be exercised directly by
the unit tests. Everything that reaches a subprocess argument vector, a Nix
expression, a systemd unit name, or a Caddy snippet passes through here
first.

Each validator returns the normalised value rather than a bool, so callers
cannot accidentally use an unvalidated original.
"""

import ipaddress
import re

from .errors import ValidationError

# Sandbox names become systemd instance names, hostnames, state directory
# components, and Nix derivation name fragments, so they are restricted to
# the intersection of what all four accept.
NAME_RE = re.compile(r"\A[a-z0-9](?:[a-z0-9-]{0,30}[a-z0-9])?\Z")

# Names that would collide with entries microvm.nix or sandcastle keep inside
# the state tree, or that read as a command rather than a sandbox.
RESERVED_NAMES = frozenset(
    {
        "all",
        "booted",
        "current",
        "lost+found",
        "previous",
        "sandcastle",
        "toplevel",
    }
)

# A nixpkgs attribute path such as `nodejs`, `python3`, or `nodePackages.pnpm`.
# Quotes, whitespace, and interpolation characters are excluded so the path can
# be spliced into a Nix expression as a literal attribute path.
PACKAGE_ATTR_RE = re.compile(r"\A[A-Za-z_][A-Za-z0-9_-]*(?:\.[A-Za-z_][A-Za-z0-9_-]*){0,3}\Z")

MAX_PACKAGES = 64
MAX_PACKAGE_ATTR_LENGTH = 80

MAC_RE = re.compile(r"\A(?:[0-9a-f]{2}:){5}[0-9a-f]{2}\Z")
MACHINE_ID_RE = re.compile(r"\A[0-9a-f]{32}\Z")

# systemd treats the all-zero ID as "unset" and silently falls back to the
# SMBIOS UUID, so a sandbox carrying it would quietly lose the identity the
# CLI allocated for it.
NULL_MACHINE_ID = "0" * 32

HOSTNAME_LABEL_RE = re.compile(r"\A[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\Z")

# 0, 1, and 2 are reserved by the VSOCK address family for the hypervisor,
# loopback, and host respectively. 0xffffffff is VMADDR_CID_ANY.
MIN_VSOCK_CID = 3
MAX_VSOCK_CID = 0xFFFFFFFE

MIN_VCPU = 1
MAX_VCPU = 32
MIN_MEMORY_MIB = 512
MAX_MEMORY_MIB = 131072
MIN_DISK_MIB = 1024
MAX_DISK_MIB = 1048576


def validate_name(value):
    """Return a validated sandbox name."""
    if not isinstance(value, str):
        raise ValidationError("sandbox name must be a string")
    if not NAME_RE.match(value):
        raise ValidationError(
            f"invalid sandbox name {value!r}: use 1-32 lowercase letters, digits, "
            "and internal hyphens"
        )
    if value in RESERVED_NAMES:
        raise ValidationError(f"sandbox name {value!r} is reserved")
    return value


def validate_package_attr(value):
    """Return a validated nixpkgs attribute path."""
    if not isinstance(value, str):
        raise ValidationError("package attribute must be a string")
    if len(value) > MAX_PACKAGE_ATTR_LENGTH:
        raise ValidationError(f"package attribute {value!r} is too long")
    if not PACKAGE_ATTR_RE.match(value):
        raise ValidationError(
            f"invalid package attribute {value!r}: expected a nixpkgs attribute "
            "path such as 'nodejs' or 'nodePackages.pnpm'"
        )
    return value


def validate_packages(values):
    """Return a sorted, de-duplicated list of validated attribute paths."""
    if isinstance(values, str) or not isinstance(values, (list, tuple)):
        raise ValidationError("packages must be a list of nixpkgs attribute paths")
    validated = {validate_package_attr(value) for value in values}
    if len(validated) > MAX_PACKAGES:
        raise ValidationError(f"at most {MAX_PACKAGES} packages may be requested")
    return sorted(validated)


def validate_port(value):
    """Return a validated TCP port number."""
    port = _as_int(value, "port")
    if not 1 <= port <= 65535:
        raise ValidationError(f"port {port} is outside 1-65535")
    return port


def validate_ipv4(value, subnet=None, forbidden=()):
    """Return a validated IPv4 address, optionally constrained to `subnet`."""
    if not isinstance(value, str):
        raise ValidationError("IPv4 address must be a string")
    try:
        address = ipaddress.IPv4Address(value)
    except ipaddress.AddressValueError as error:
        raise ValidationError(f"invalid IPv4 address {value!r}: {error}") from error

    if subnet is not None:
        network = ipaddress.IPv4Network(subnet, strict=True)
        if address not in network:
            raise ValidationError(f"{address} is outside the sandbox subnet {network}")
        if network.prefixlen < 31 and address in (
            network.network_address,
            network.broadcast_address,
        ):
            raise ValidationError(f"{address} is the network or broadcast address of {network}")

    for reserved in forbidden:
        if address == ipaddress.IPv4Address(reserved):
            raise ValidationError(f"{address} is reserved by the host")

    return str(address)


def validate_mac(value):
    """Return a validated locally administered unicast MAC address."""
    if not isinstance(value, str):
        raise ValidationError("MAC address must be a string")
    normalised = value.lower()
    if not MAC_RE.match(normalised):
        raise ValidationError(f"invalid MAC address {value!r}: expected aa:bb:cc:dd:ee:ff")
    first = int(normalised[0:2], 16)
    if first & 0x01:
        raise ValidationError(f"MAC address {value!r} is a multicast address")
    if not first & 0x02:
        raise ValidationError(
            f"MAC address {value!r} is not locally administered; the second-least "
            "significant bit of the first octet must be set"
        )
    return normalised


def validate_vsock_cid(value):
    """Return a validated VSOCK context ID."""
    cid = _as_int(value, "VSOCK CID")
    if not MIN_VSOCK_CID <= cid <= MAX_VSOCK_CID:
        raise ValidationError(
            f"VSOCK CID {cid} is outside {MIN_VSOCK_CID}-{MAX_VSOCK_CID}; "
            "0, 1, and 2 are reserved"
        )
    return cid


def validate_machine_id(value):
    """Return a validated systemd machine ID."""
    if not isinstance(value, str) or not MACHINE_ID_RE.match(value):
        raise ValidationError("machine ID must be 32 lowercase hexadecimal characters")
    if value == NULL_MACHINE_ID:
        raise ValidationError(
            "machine ID must not be all zeroes: systemd rejects the null ID and "
            "would fall back to the hypervisor's SMBIOS UUID"
        )
    return value


def validate_hostname(value, zone=None):
    """Return a validated DNS hostname, optionally inside `zone`."""
    if not isinstance(value, str):
        raise ValidationError("hostname must be a string")
    hostname = value.rstrip(".").lower()
    if not hostname or len(hostname) > 253:
        raise ValidationError(f"invalid hostname {value!r}: must be 1-253 characters")
    labels = hostname.split(".")
    for label in labels:
        if not HOSTNAME_LABEL_RE.match(label):
            raise ValidationError(f"invalid hostname label {label!r} in {value!r}")

    if zone is not None:
        zone = zone.rstrip(".").lower()
        if not hostname.endswith("." + zone):
            raise ValidationError(f"hostname {hostname} is not a subdomain of {zone}")
        if hostname == zone:
            raise ValidationError(f"hostname {hostname} is the zone apex")

    return hostname


def validate_vcpu(value):
    return _as_bounded_int(value, "vcpu", MIN_VCPU, MAX_VCPU)


def validate_memory_mib(value):
    return _as_bounded_int(value, "memoryMiB", MIN_MEMORY_MIB, MAX_MEMORY_MIB)


def validate_disk_mib(value):
    return _as_bounded_int(value, "homeDiskMiB", MIN_DISK_MIB, MAX_DISK_MIB)


def validate_line_count(value):
    """Return a validated journal line count."""
    return _as_bounded_int(value, "line count", 1, 1000000)


# Store paths are spliced into the Nix expression the CLI evaluates, so they
# are checked against the exact shape `nix-store --add` produces.
STORE_PATH_RE = re.compile(r"\A/nix/store/[0-9a-df-np-sv-z]{32}-[A-Za-z0-9+._?=-]+\Z")


def validate_store_path(value):
    """Return a validated /nix/store path."""
    if not isinstance(value, str) or not STORE_PATH_RE.match(value):
        raise ValidationError(f"{value!r} is not a /nix/store path")
    return value


def _as_int(value, what):
    if isinstance(value, bool) or not isinstance(value, int):
        if isinstance(value, str):
            try:
                return int(value, 10)
            except ValueError as error:
                raise ValidationError(f"{what} must be an integer, got {value!r}") from error
        raise ValidationError(f"{what} must be an integer, got {value!r}")
    return value


def _as_bounded_int(value, what, low, high):
    number = _as_int(value, what)
    if not low <= number <= high:
        raise ValidationError(f"{what} {number} is outside {low}-{high}")
    return number
