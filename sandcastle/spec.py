"""The versioned JSON sandbox specification.

A spec records only non-secret desired state. Credentials and Caddy routes
are deliberately kept in separate trees so a fork can copy the spec without
inheriting either.

The on-disk document is the contract between the CLI and the Nix builder, so
every field is validated on the way in and on the way out.
"""

import datetime
import json
import uuid
from dataclasses import asdict, dataclass, field, replace

from . import validate
from .errors import StateError, ValidationError

CURRENT_SCHEMA_VERSION = 1

# Agent CLIs a sandbox may opt into. These are attribute names in the
# llm-agents overlay rather than free-form nixpkgs paths.
KNOWN_AGENTS = ("claude-code", "codex")

DEFAULT_VCPU = 2
DEFAULT_MEMORY_MIB = 2304
DEFAULT_HOME_DISK_MIB = 16384

# Package sets `create` and `packages add` accept in place of a list of
# nixpkgs attribute paths.
PROFILES = {
    "node": ["nodejs", "pnpm"],
    "python": ["python3", "uv"],
    "go": ["go", "gopls"],
    "rust": ["rustc", "cargo", "pkg-config", "gcc"],
}


@dataclass(frozen=True)
class Spec:
    """One sandbox's desired state."""

    name: str
    ipv4: str
    mac: str
    vsock_cid: int
    machine_id: str
    vcpu: int = DEFAULT_VCPU
    memory_mib: int = DEFAULT_MEMORY_MIB
    home_disk_mib: int = DEFAULT_HOME_DISK_MIB
    packages: list = field(default_factory=list)
    agents: list = field(default_factory=lambda: list(KNOWN_AGENTS))
    repo_url: str = ""
    repo_branch: str = ""
    created_at: str = ""
    parent: str = ""

    def to_dict(self):
        """Return the on-disk document for this spec."""
        return {
            "schemaVersion": CURRENT_SCHEMA_VERSION,
            "name": self.name,
            "vcpu": self.vcpu,
            "memoryMiB": self.memory_mib,
            "homeDiskMiB": self.home_disk_mib,
            "packages": list(self.packages),
            "agents": list(self.agents),
            "ipv4": self.ipv4,
            "mac": self.mac,
            "vsockCid": self.vsock_cid,
            "machineId": self.machine_id,
            "repoUrl": self.repo_url,
            "repoBranch": self.repo_branch,
            "createdAt": self.created_at,
            "parent": self.parent,
        }

    def to_json(self):
        return json.dumps(self.to_dict(), indent=2, sort_keys=True) + "\n"

    def with_packages(self, packages):
        return replace(self, packages=validate.validate_packages(packages))

    def as_row(self):
        """Flat mapping used by `list` and `status` output."""
        return asdict(self)


_FIELD_KEYS = {
    "name": "name",
    "vcpu": "vcpu",
    "memoryMiB": "memory_mib",
    "homeDiskMiB": "home_disk_mib",
    "packages": "packages",
    "agents": "agents",
    "ipv4": "ipv4",
    "mac": "mac",
    "vsockCid": "vsock_cid",
    "machineId": "machine_id",
    "repoUrl": "repo_url",
    "repoBranch": "repo_branch",
    "createdAt": "created_at",
    "parent": "parent",
}

# Maps a schema version to the function that upgrades a document of that
# version to the next one. Empty while version 1 is the only version; the
# loader below is written against the registry so adding an entry is the
# only change a future schema bump needs.
_MIGRATIONS = {}


def migrate(document):
    """Upgrade a parsed spec document to the current schema version."""
    if not isinstance(document, dict):
        raise StateError("sandbox spec must be a JSON object")

    version = document.get("schemaVersion")
    if not isinstance(version, int) or isinstance(version, bool):
        raise StateError("sandbox spec is missing an integer schemaVersion")
    if version < 1:
        raise StateError(f"sandbox spec schemaVersion {version} is not a released version")
    if version > CURRENT_SCHEMA_VERSION:
        raise StateError(
            f"sandbox spec schemaVersion {version} was written by a newer sandcastle; "
            f"this build understands up to {CURRENT_SCHEMA_VERSION}"
        )

    document = dict(document)
    while version < CURRENT_SCHEMA_VERSION:
        step = _MIGRATIONS.get(version)
        if step is None:
            raise StateError(f"no migration from sandbox spec schemaVersion {version}")
        document = step(document)
        version += 1
        document["schemaVersion"] = version

    return document


def from_dict(document, config=None):
    """Validate a parsed document and return a Spec."""
    document = migrate(document)

    unknown = sorted(set(document) - set(_FIELD_KEYS) - {"schemaVersion"})
    if unknown:
        raise StateError(f"unknown sandbox spec keys: {', '.join(unknown)}")

    missing = sorted(
        key for key in ("name", "ipv4", "mac", "vsockCid", "machineId") if key not in document
    )
    if missing:
        raise StateError(f"sandbox spec is missing required keys: {', '.join(missing)}")

    subnet = config.subnet if config is not None else None
    values = {_FIELD_KEYS[key]: value for key, value in document.items() if key in _FIELD_KEYS}

    spec = Spec(
        name=validate.validate_name(values["name"]),
        ipv4=validate.validate_ipv4(values["ipv4"], subnet=subnet),
        mac=validate.validate_mac(values["mac"]),
        vsock_cid=validate.validate_vsock_cid(values["vsock_cid"]),
        machine_id=validate.validate_machine_id(values["machine_id"]),
        vcpu=validate.validate_vcpu(values.get("vcpu", DEFAULT_VCPU)),
        memory_mib=validate.validate_memory_mib(values.get("memory_mib", DEFAULT_MEMORY_MIB)),
        home_disk_mib=validate.validate_disk_mib(
            values.get("home_disk_mib", DEFAULT_HOME_DISK_MIB)
        ),
        packages=validate.validate_packages(values.get("packages", [])),
        agents=validate_agents(values.get("agents", list(KNOWN_AGENTS))),
        repo_url=_as_optional_str(values.get("repo_url"), "repoUrl"),
        repo_branch=_as_optional_str(values.get("repo_branch"), "repoBranch"),
        created_at=_as_optional_str(values.get("created_at"), "createdAt"),
        parent=_as_optional_str(values.get("parent"), "parent"),
    )

    if spec.parent:
        validate.validate_name(spec.parent)
    return spec


def from_json(text, config=None):
    try:
        document = json.loads(text)
    except json.JSONDecodeError as error:
        raise StateError(f"sandbox spec is not valid JSON: {error}") from error
    return from_dict(document, config=config)


def validate_agents(values):
    """Return a sorted, de-duplicated list of validated agent names."""
    if isinstance(values, str) or not isinstance(values, (list, tuple)):
        raise ValidationError("agents must be a list")
    unknown = sorted(set(values) - set(KNOWN_AGENTS))
    if unknown:
        raise ValidationError(
            f"unknown agents: {', '.join(unknown)}; known agents are {', '.join(KNOWN_AGENTS)}"
        )
    return sorted(set(values))


def expand_packages(requested):
    """Expand profile names and validate the resulting attribute paths."""
    expanded = []
    for entry in requested:
        expanded.extend(PROFILES.get(entry, [entry]))
    return validate.validate_packages(expanded)


def new_machine_id():
    return uuid.uuid4().hex


def now_iso():
    return datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _as_optional_str(value, what):
    if value is None:
        return ""
    if not isinstance(value, str):
        raise StateError(f"{what} must be a string")
    return value
