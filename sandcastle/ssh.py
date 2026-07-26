"""Host-to-guest SSH over VSOCK.

No guest SSH port is forwarded or opened publicly. Every sandbox gets a
unique VSOCK context ID, and the host reaches it as the destination
`vsock/<cid>`, which `systemd-ssh-proxy` turns into an AF_VSOCK connection.

Two pieces of key material are involved and they are deliberately different:

- the *control key*, one per installation, whose public half is baked into
  every guest closure so the CLI can log in as `dev`;
- each guest's own *host key*, which the guest generates on its persistent
  identity volume and the CLI pins in a per-sandbox known-hosts file.
"""

import os
import shutil
import subprocess

from . import state, validate
from .errors import LifecycleError, StateError

GUEST_USER = "dev"

CONTROL_KEY_TYPE = "ed25519"
CONTROL_KEY_COMMENT = "sandcastle-control"

KEY_MODE = 0o600
PUBLIC_KEY_MODE = 0o644


def ssh_binary():
    return os.environ.get("SANDCASTLE_SSH", "ssh")


def ssh_keygen_binary():
    return os.environ.get("SANDCASTLE_SSH_KEYGEN", "ssh-keygen")


def public_key_path(config):
    return config.control_key_path + ".pub"


def ensure_control_key(config):
    """Return the public control key, generating the pair if it is missing.

    The private half never leaves the state tree. The public half is a build
    input rather than part of the persisted specification, so rotating the
    control key is a rebuild of every sandbox rather than a rewrite of every
    specification.
    """
    public_path = public_key_path(config)
    if os.path.exists(config.control_key_path) and os.path.exists(public_path):
        return read_public_key(config)

    os.makedirs(config.ssh_dir, mode=0o700, exist_ok=True)
    # ssh-keygen refuses to overwrite, and a half-written pair from an
    # interrupted run would be one such leftover.
    for path in (config.control_key_path, public_path):
        if os.path.exists(path):
            os.unlink(path)

    binary = ssh_keygen_binary()
    if shutil.which(binary) is None:
        raise StateError(f"cannot create the sandcastle control key: {binary} is not on PATH")

    completed = subprocess.run(
        [
            binary,
            "-t",
            CONTROL_KEY_TYPE,
            "-N",
            "",
            "-C",
            CONTROL_KEY_COMMENT,
            "-f",
            config.control_key_path,
        ],
        check=False,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    if completed.returncode != 0:
        detail = completed.stderr.strip() or completed.stdout.strip()
        raise StateError(f"failed to create the sandcastle control key:\n{detail}")

    os.chmod(config.control_key_path, KEY_MODE)
    os.chmod(public_path, PUBLIC_KEY_MODE)
    return read_public_key(config)


def read_public_key(config):
    """Return the single-line public control key."""
    path = public_key_path(config)
    try:
        with open(path, "r", encoding="utf-8") as handle:
            text = handle.read().strip()
    except FileNotFoundError:
        raise StateError(f"the sandcastle control key {path} does not exist") from None
    if not text or "\n" in text:
        raise StateError(f"{path} is not a single-line OpenSSH public key")
    return text


def ensure_known_hosts(config, name):
    """Return the per-sandbox known-hosts path, creating an empty file."""
    name = validate.validate_name(name)
    os.makedirs(config.known_hosts_dir, mode=0o700, exist_ok=True)
    path = config.known_hosts_path(name)
    if not os.path.exists(path):
        state.atomic_write_text(path, "", mode=KEY_MODE)
    return path


def forget_known_hosts(config, name):
    """Drop a sandbox's pinned guest host key. Used by `delete`."""
    path = config.known_hosts_path(validate.validate_name(name))
    try:
        os.unlink(path)
    except FileNotFoundError:
        return False
    return True


def destination(spec):
    """Return the `ssh` destination for a sandbox's VSOCK context ID."""
    return f"vsock/{validate.validate_vsock_cid(spec.vsock_cid)}"


def ssh_command(
    config,
    spec,
    *,
    agent_forwarding=False,
    ssh_options=(),
    remote_command=(),
):
    """Return the argv that opens a session on `spec` as the `dev` user.

    Options are placed on the command line rather than in a generated
    configuration file because the first value ssh sees wins: these therefore
    override the `Host vsock/*` block in /etc/ssh/ssh_config, which
    deliberately disables host-key checking for ephemeral VSOCK addresses.
    """
    known_hosts = ensure_known_hosts(config, spec.name)
    if not os.path.exists(config.control_key_path):
        raise StateError(
            f"the sandcastle control key {config.control_key_path} does not exist; "
            "run sandcastle create or sandcastle build to create it"
        )

    command = [
        ssh_binary(),
        "-o",
        f"UserKnownHostsFile={known_hosts}",
        # The guest keeps its host key on a persistent identity volume, so the
        # first connection pins it and any later change is a hard failure.
        "-o",
        "StrictHostKeyChecking=accept-new",
        "-o",
        f"IdentityFile={config.control_key_path}",
        "-o",
        "IdentitiesOnly=yes",
        "-o",
        "PasswordAuthentication=no",
        "-o",
        f"User={GUEST_USER}",
    ]

    if config.ssh_proxy:
        command += [
            "-o",
            f"ProxyCommand={config.ssh_proxy} %h %p",
            "-o",
            "ProxyUseFdpass=yes",
        ]

    if agent_forwarding:
        if not os.environ.get("SSH_AUTH_SOCK"):
            raise LifecycleError(
                "agent forwarding was requested but SSH_AUTH_SOCK is not set; "
                "run sudo --preserve-env=SSH_AUTH_SOCK sandcastle ssh ..."
            )
        command.append("-A")
    else:
        # Without opt-in forwarding the operator's agent stays out of the
        # guest entirely, rather than merely being unused for authentication.
        command += ["-o", "IdentityAgent=none", "-o", "ForwardAgent=no"]

    command += list(ssh_options)
    command.append(destination(spec))
    command += list(remote_command)
    return command


def exec_ssh(command):  # pragma: no cover - replaces this process
    """Hand the terminal to ssh. Never returns on success."""
    binary = command[0]
    if shutil.which(binary) is None:
        raise LifecycleError(f"cannot connect to the sandbox: {binary} is not on PATH")
    os.execvp(binary, command)
