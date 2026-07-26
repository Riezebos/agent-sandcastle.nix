# Agent Sandcastle — CLI-First Plan

Agent Sandcastle is a small Nix package and NixOS module for managing isolated
development MicroVMs on a personal NixOS server.

The operator SSHes into the server and uses a local `sandcastle` command to
create, start, stop, inspect, enter, fork, and expose sandboxes. There is no web
control plane, database, daemon, lifecycle broker, or mobile session service.

This plan supersedes the earlier Phoenix/Authentik/Happy control-plane design.

## 1. Problem to solve

The intended workflow is:

1. SSH into a NixOS server.
2. Create development sandboxes backed by `microvm.nix`.
3. Add development tools without maintaining a general mutable guest Nix
   store.
4. SSH into each sandbox without allocating public SSH ports.
5. Fork a sandbox while preserving its uncommitted filesystem state.
6. Run development web servers inside sandboxes.
7. Expose selected ports on subdomains of `simonito.com`, either publicly or
   behind Authentik.

The initial target is one trusted operator running a small number of trusted
development workloads on the existing `foundry` server.

## 2. Goals and non-goals

### Goals

- A boring SSH-first workflow with one `sudo sandcastle ...` CLI.
- MicroVM isolation through `microvm.nix` and KVM.
- Persistent project state under `/home/dev`.
- Immutable guest system closures rebuilt from a small sandbox specification.
- Additional packages selected per sandbox.
- `uv`, `pnpm`, and similar project-level package managers working normally.
- Host-to-guest SSH over VSOCK.
- Exact filesystem forks through a simple, reliable disk-copy implementation.
- Stable guest addresses for Caddy reverse proxying.
- Per-route public or Authentik-protected web exposure.
- No direct public ingress to guest networks.
- A clear later path from a development server to a separately deployed
  production service.

### Non-goals

- A browser UI or remote HTTP API.
- Multi-user or multi-tenant authorization.
- A long-running privileged daemon.
- Phoenix, LiveView, SQLite, or a lifecycle broker.
- Happy mobile sessions or a self-hosted Happy relay.
- Instant qcow2 backing-chain forks in the first version.
- Treating a development MicroVM as a production deployment platform.
- A fully mutable NixOS guest.
- Automatic Git provider OAuth, deploy-key management, or branch-protection
  automation.

## 3. Architecture

The project has four small parts:

1. **CLI package**
   - A Python standard-library application packaged by Nix.
   - Runs only when invoked by the operator through `sudo`.
   - Owns sandbox specifications, lifecycle calls, disk copying, and Caddy
     snippets.
   - Uses argument-vector subprocess calls rather than shell interpolation.

2. **Host NixOS module**
   - Imports the `microvm.nix` host module.
   - Installs the CLI and its fixed runtime dependencies.
   - Configures the sandbox bridge, DNS, NAT, isolation firewall, state
     directories, systemd slice, and Caddy snippet directory.
   - Sets `microvm.stateDir = "/var/lib/sandcastle/vms"`.

3. **Guest NixOS module**
   - Creates the unprivileged `dev` user.
   - Enables OpenSSH over VSOCK.
   - Installs the base development tools and the packages selected in the
     sandbox specification.
   - Mounts a persistent raw volume at `/home/dev`.
   - Uses tmpfs for disposable scratch paths.
   - Keeps agent credentials outside the home disk.

4. **Sandbox builder**
   - Accepts a validated JSON sandbox specification.
   - Evaluates a NixOS MicroVM configuration.
   - Builds `config.microvm.declaredRunner`.
   - Installs the runner atomically into the sandbox state directory and keeps
     it alive through a Nix GC root.

There is no separate control-plane process:

```text
operator over SSH
        |
        v
sudo sandcastle
        |
        +--> JSON specs and VM disks under /var/lib/sandcastle
        +--> Nix builds immutable MicroVM runners
        +--> systemd microvm@<name>.service
        +--> validated Caddy snippets and reloads
```

## 4. Command-line workflow

The target command surface is:

```sh
# Inventory and creation
sudo sandcastle list
sudo sandcastle create my-app --packages nodejs pnpm uv python3
sudo sandcastle status my-app

# Lifecycle
sudo sandcastle start my-app
sudo sandcastle stop my-app
sudo sandcastle restart my-app
sudo sandcastle rebuild my-app
sudo sandcastle logs my-app

# Guest access
sudo sandcastle ssh my-app
sudo sandcastle ssh my-app -- -A

# Packages
sudo sandcastle packages list my-app
sudo sandcastle packages add my-app go
sudo sandcastle packages remove my-app python3

# Forking
sudo sandcastle fork my-app alternate-approach

# Web routes
sudo sandcastle expose my-app \
  --port 3000 \
  --host my-app.simonito.com \
  --auth public
sudo sandcastle expose internal-tool \
  --port 8000 \
  --host internal-tool.simonito.com \
  --auth authentik
sudo sandcastle routes
sudo sandcastle unexpose my-app.simonito.com

# Destructive lifecycle
sudo sandcastle delete my-app
sudo sandcastle delete my-app --delete-credentials --yes
```

Names, hostnames, package attributes, ports, paths, and identifiers are
validated before any build or mutation.

## 5. Runtime state

All mutable state belongs beneath one root-owned tree:

```text
/var/lib/sandcastle/
  specs/
    my-app.json
  vms/
    my-app/
      current -> /nix/store/...-microvm-run
      booted -> /nix/store/...-microvm-run
      home.img
      identity.img
  credentials/
    my-app/
      codex/
      claude/
  caddy/
    my-app.simonito.com.caddy
  locks/
  known-hosts/
  ssh/
    control_ed25519
```

`identity.img` is a small persistent volume holding only the guest's own SSH
host key. It is separate from `home.img` because a fork copies project state
but must not inherit the parent's guest identity, and because the host key has
to survive a reboot for host-key pinning to mean anything.

`ssh/control_ed25519` is one key pair per installation, not per sandbox. Its
private half is the only thing that can log into a sandbox as `dev`.

The JSON specification records only non-secret desired state:

- schema version;
- sandbox name;
- CPU, memory, and home-disk size;
- package attribute names;
- static IPv4 address;
- MAC address;
- VSOCK CID;
- machine identity;
- optional repository metadata;
- creation and parent identifiers.

Routes are separate from the sandbox specification so forks never inherit
public exposure. Credentials are also separate so forks never inherit agent
or Git credentials.

Some values the guest needs at build time are deliberately *not* spec fields.
The bridge gateway, prefix length, and resolvers, and the public half of the
control key, are composed into the build input from the host configuration
instead. Moving the subnet or rotating the control key is therefore a rebuild
of every sandbox rather than a rewrite of every specification.

Each mutation uses a global allocation lock plus a per-sandbox lock. Files are
written to a sibling temporary path and atomically renamed into place.

## 6. Guest package model

The first version deliberately avoids a writable Nix store.

The immutable guest system contains:

- shell and core utilities;
- Git, OpenSSH, curl, jq, ripgrep, tmux, an editor, and basic diagnostics;
- optional Claude Code and Codex packages;
- the per-sandbox packages declared in its specification.

Package arguments are validated nixpkgs attribute paths, resolved without
evaluating user-provided Nix source. Convenience profiles may expand to common
sets:

- `node`: Node.js and pnpm;
- `python`: Python and uv;
- `go`: Go toolchain;
- `rust`: Rust toolchain and common native build tools.

Changing the package list rebuilds the immutable runner and requires a guest
restart. The CLI builds the replacement first, switches the `current` symlink
atomically, and restores the previous runner if activation fails.

Project dependencies remain on `/home/dev`:

- pnpm project stores and `node_modules`;
- uv-managed virtual environments;
- source checkouts;
- uncommitted changes;
- editor and shell configuration.

This keeps guest package management predictable without taking on
`microvm.nix` writable-store overlay and Nix database persistence caveats.

## 7. Lifecycle implementation

The CLI builds on the conventions already provided by `microvm.nix`:

- runner installed at `<stateDir>/<name>/current`;
- `microvm@<name>.service` for the hypervisor;
- companion TAP and virtiofsd template units;
- `booted` runner tracking;
- graceful shutdown through the runner;
- a GC root for every installed runner.

### Create

`create`:

1. Validates and reserves the name, IP, MAC, VSOCK CID, and machine identity.
2. Writes a proposed specification.
3. Checks that the declared disks plus headroom will fit.
4. Creates an empty credentials directory.
5. Builds the runner.
6. Installs the runner and GC root atomically.
7. Leaves the VM stopped unless `--start` is provided.

`create` does not create the disk images. microvm.nix's runner creates and
formats a declared volume on first boot, but only when the image file does not
already exist, so pre-creating one would leave an unformatted disk the runner
then refuses to format. Free space is therefore checked rather than claimed.

Failure after the name is reserved releases everything the create reserved: the
specification, the VM directory, the GC roots, the known-hosts entry, and the
credentials directory *unless it already existed*, because a previous `delete`
may have deliberately kept it. A failed create must not leave a partially
addressable VM, and must not destroy credentials it did not create.

### Rebuild

`rebuild`:

1. Builds a candidate runner without changing the installed runner.
2. Replaces `current` atomically.
3. Restarts the guest if it was running, or if `--restart` is given.
4. Confirms the guest actually came up.
5. Restores the old runner and restarts it if activation fails.

The VM is not stopped before `current` moves. microvm.nix's `booted` symlink
still points at the runner the guest was started from, so the unit's
`ExecStop` shuts it down correctly across the change, and there is no window
where the sandbox is down on an untested runner.

Step 4 is not optional bookkeeping. Only cloud-hypervisor reports readiness
over a notify socket, so a QEMU sandbox's `microvm@<name>.service` is
`Type=simple` with `Restart=always`: `systemctl start` succeeds for a guest
that cannot boot, and the failure hides inside a restart loop. Activation is
therefore confirmed by watching the unit hold a single invocation in a running
state for a few seconds. Without that check the rollback in step 5 would never
fire.

### Delete

`delete`:

- refuses to delete a running VM;
- refuses while the sandbox still owns Caddy routes, so a route can never be
  left pointing at an address the next `create` hands to a different sandbox;
- requires `--yes`;
- keeps credentials unless `--delete-credentials` is explicit;
- removes only the resolved sandbox state directory and GC root;
- reports which data was removed and whether credentials remain.

## 8. SSH and identity

Each VM receives a unique VSOCK CID and enables the `microvm.nix` VSOCK SSH
support. The wrapper connects as `dev`:

```sh
sudo sandcastle ssh my-app
```

No guest SSH port is forwarded or opened publicly. The destination is
`vsock/<cid>`, which `systemd-ssh-proxy` turns into an AF_VSOCK connection.

`microvm.vsock.ssh.enable` is necessary but not sufficient. The guest's
`sshd-vsock.socket` is written by `systemd-ssh-generator`, which only emits it
when `/dev/vsock` already exists; generators run before udev can autoload the
virtio transport from the device's modalias. The guest must therefore load
`vmw_vsock_virtio_transport` from its initrd. Without that it boots perfectly
and listens only on the AF_UNIX local socket, so this fails as a working VM
rather than as a build error.

### Two kinds of key material

These are deliberately different and must not be conflated:

- one **control key** per installation, in `<stateDir>/ssh/`. Created on first
  use; its public half is a build input, so every guest closure accepts it for
  the `dev` user. Rotating it is a rebuild of every sandbox. It is the
  operator's key, not sandbox state, so a fork does inherit it.
- each guest's **own host key**, generated inside the guest onto its
  `identity.img` volume. The CLI pins it in a per-sandbox known-hosts file on
  first connect and checks it strictly afterwards. This is sandbox state, so a
  fork must not inherit it.

Command-line `-o` settings carry the known-hosts path and strictness, because
the `Host vsock/*` block in `/etc/ssh/ssh_config` deliberately disables
host-key checking for ephemeral VSOCK addresses and ssh honours the first value
it sees.

Each sandbox has a distinct machine identity and SSH host identity. Note that
`systemd.machine_id=` on the kernel command line is ignored for the all-zero
ID, and systemd then falls back to the hypervisor's SMBIOS UUID, so the
allocated identity must be validated as non-null.

Agent forwarding is opt-in and is the initial solution for cloning private Git
repositories without storing deploy keys in the guest. Without it the
operator's agent is kept out of the guest entirely rather than merely unused
for authentication.

## 9. Networking

The host retains a dedicated TAP bridge, initially `10.88.0.0/24`.

Each sandbox receives a static address allocated by the CLI. Static addressing
keeps Caddy routes stable and removes DHCP lease discovery from lifecycle
operations. The host bridge continues to provide guest DNS.

The simplified egress policy is:

- allow public internet destinations;
- reject the host except for DNS;
- reject traffic between sandboxes;
- reject loopback, RFC1918, carrier-grade NAT, link-local, metadata, multicast,
  and other non-public address ranges;
- do not expose the bridge through the host's public firewall.

The earlier exact-hostname-to-IP allowlist is removed. It is too brittle for
package managers, source forges, CDNs, and general trusted development work.

Guests accept development-server connections from the host bridge. Caddy is
the only intended path from the public internet to a guest application.

## 10. Forking

The first version uses stopped, sparse raw-disk copying instead of qcow2
backing chains.

`fork parent child`:

1. Locks both names.
2. Records whether the parent is running.
3. Stops the parent and waits for a clean shutdown.
4. Copies the raw home disk with `qemu-img convert` using sparse output.
5. Copies the non-secret package and resource specification.
6. Allocates a new IP, MAC, VSOCK CID, and machine identity.
7. Creates an empty child credentials directory.
8. Builds and installs the child runner.
9. Restarts the parent if it was previously running.
10. Leaves the child stopped unless `--start` is provided.

Only `home.img` is copied. The child gets a fresh guest SSH host identity for
free: `identity.img` is simply not copied, and the child generates its own key
on first boot. No key needs to be generated, injected, or scrubbed out of the
copied filesystem.

The child inherits source files, uncommitted changes, virtual environments,
Node dependencies, and other home-directory state. It does not inherit:

- Codex or Claude credentials;
- Git credentials;
- Caddy routes;
- network or machine identity;
- the guest SSH host key;
- process or memory state.

This is O(used disk data), not O(1), but has no backing-chain bookkeeping and
works with the current QEMU runner's raw volume behavior. Add qcow2 branching
only after measured fork time justifies the additional format, snapshot,
flattening, and failure-recovery complexity.

## 11. Web application exposure

The downstream Caddy configuration imports:

```text
/var/lib/sandcastle/caddy/*.caddy
```

The directory always contains a harmless placeholder so a missing glob cannot
break Caddy evaluation.

`expose`:

1. Validates the hostname is an allowed subdomain of `simonito.com`.
2. Rejects reserved or already configured hostnames.
3. Validates the port and sandbox address.
4. Writes an exact-host Caddy snippet atomically.
5. Selects either public routing or the existing Authentik `forward_auth`
   pattern.
6. Runs Caddy configuration validation.
7. Reloads Caddy only if validation succeeds.

`unexpose` removes the route atomically and reloads Caddy. Routes target the
sandbox's stable bridge address and selected port.

The application must listen on `0.0.0.0`, not guest loopback. Initially the
operator runs development servers in `tmux`. A declarative guest dev-server
unit is deferred until repeated use demonstrates that it is worthwhile.

## 12. Credentials

The web launcher's opaque-ID broker design is no longer necessary because the
trusted operator invokes the CLI locally through `sudo`.

Secrets still remain outside the forked home disk:

- Codex receives a separate writable auth mount.
- Claude receives a separate credential mount or environment file.
- Git initially uses opt-in SSH agent forwarding.

Credential directories are root-owned, excluded from logs, and excluded from
sandbox forks. Sandbox deletion retains credentials by default to prevent an
accidental irreversible logout.

Credential enrollment and rotation commands may be added after the basic CLI
lifecycle is stable. They do not require a daemon.

## 13. Shared-host safety

Foundry also runs unrelated services, so Sandcastle keeps explicit limits:

- one dedicated systemd slice;
- aggregate memory and CPU limits;
- process, file-descriptor, and task limits;
- disk-space checks before create and fork;
- at most a small configured number of concurrently running VMs;
- journald limits;
- no direct access from guests to Foundry, Authentik, PostgreSQL, monitoring,
  backups, or the LAN.

The initial workload remains trusted, single-user development. Move the whole
Sandcastle state tree and host module to a dedicated KVM server if workloads
become untrusted, more users gain access, sustained resource contention
appears, or the state becomes materially sensitive.

Sandbox disks are not production data and are not backed up by default.
Specifications may be backed up, but source work should be committed and
pushed. The CLI should warn about this in `create` output and documentation.

## 14. Repository and flake shape

The intended repository layout is:

```text
agent-sandcastle.nix/
  flake.nix
  nix/
    host-module.nix
    guest-module.nix
    sandbox-builder.nix
    sandbox-network.nix
    sandcastle-package.nix
  sandcastle/
    __main__.py
    cli.py
    config.py
    errors.py
    validate.py
    spec.py
    state.py
    build.py
    systemd.py
    ssh.py
    lifecycle.py
    routes.py
  tests/
  examples/
  README.md
  PLAN.md
  PROGRESS.md
```

Target flake outputs:

- `packages.x86_64-linux.sandcastle`
- `packages.x86_64-linux.sandbox-smoke`
- `apps.x86_64-linux.sandcastle`
- `nixosModules.default`
- `nixosModules.host`
- `nixosModules.guest`
- `lib.mkSandbox`
- build, evaluation, CLI unit, and smoke checks

Claude Code and Codex remain optional guest packages from
`numtide/llm-agents.nix`. Happy is removed.

## 15. Migration from the current implementation

Migration is staged so the deployed dry-run launcher is not removed before the
CLI replacement works.

### Phase A — Build alongside the launcher

- Add the CLI package and new host options.
- Add the JSON-to-runner builder.
- Use MicroVM's per-VM store disk instead of the curated union store.
- Implement lifecycle and VSOCK SSH.
- Keep the current launcher deployment untouched.

### Phase B — Runtime smoke test

- Deploy the new host substrate to Foundry.
- Create a new `cli-smoke` sandbox.
- Validate create, boot, SSH, rebuild, stop, and delete.
- Validate package installation through the immutable spec.
- Validate the simplified egress and isolation rules.

### Phase C — Fork and route test

- Fork a VM containing uncommitted work.
- Verify parent and child diverge independently.
- Verify the child has no credentials or routes.
- Expose one public application.
- Expose one Authentik-protected application.
- Verify HTTPS, reload safety, and isolation.

### Phase D — Remove retired components

In this repository:

- remove `launcher/`;
- remove `nix/launcher.nix`;
- remove `nix/launcher-module.nix`;
- remove Phoenix/Elixir inputs, packages, checks, migrations, and dev shell;
- remove Happy packages and service wiring;
- remove the curated-store module after no VM depends on it;
- replace obsolete examples and documentation.

In the downstream `nix` repository:

- replace `agentSandcastleLauncher` with a CLI host feature;
- remove the launcher sops secret declaration;
- remove the `sandcastle.simonito.com` reverse proxy to port 4000;
- add the dynamic Caddy snippet import;
- keep Authentik for protected sandbox application routes;
- retain the old launcher state directory until it is explicitly reviewed and
  deleted.

## 16. Milestones

### M0 — Reusable substrate

- Existing MicroVM guest boots on Foundry with KVM.
- Existing TAP bridge, NAT, DNS, and isolation behavior are understood.
- Existing base guest and agent packages evaluate and build.

### M1 — CLI and state model

- Packaged Python CLI.
- Versioned JSON specifications.
- Safe allocation, validation, locking, atomic writes, and GC roots.
- Runner builder using per-VM store images.

### M2 — Lifecycle and SSH

- Create, list, status, start, stop, restart, rebuild, logs, and delete.
- Static IP and VSOCK allocation.
- `sandcastle ssh` connects as `dev`.
- Rollback after a failed rebuild.

### M3 — Packages and networking

- Per-sandbox package lists and convenience profiles.
- `uv` and `pnpm` runtime validation.
- Public-internet egress with private/internal destination blocking.
- Shared-host resource limits.

### M4 — Forking

- Clean parent shutdown.
- Sparse raw home-disk copying.
- Identity and credential separation.
- Parent/child divergence test.

### M5 — Caddy routes

- Dynamic snippet import.
- Public and Authentik route modes.
- Atomic validation and reload.
- HTTPS runtime verification.

### M6 — Cutover and cleanup

- Downstream CLI host deployment.
- Phoenix, Happy, SQLite, launcher secret, and broker plan removed.
- Curated store removed from the runtime path.
- Obsolete state retained or deleted through an explicit reviewed operation.

### M7 — Documentation and release

- README matches the real CLI.
- Operational recovery and deletion behavior documented.
- End-to-end Foundry acceptance checklist passes.
- First CLI-first tagged release.

## 17. Acceptance criteria

The initial project is complete when all of the following pass on Foundry:

- Create and start a sandbox entirely through the CLI.
- SSH into it over VSOCK as `dev`.
- Add pnpm and uv through its package specification.
- Run `pnpm install` and `uv sync`.
- Reboot and retain project state.
- Rebuild after adding and removing a Nix package.
- Fork a sandbox with an uncommitted file.
- Change the child without changing the parent.
- Confirm the child has no copied credentials or routes.
- Reach the public internet from the guest.
- Fail to reach the host, LAN, metadata endpoints, or another guest.
- Expose a public development server with valid HTTPS.
- Expose an Authentik-protected development server with valid HTTPS.
- Reject an invalid Caddy route without disturbing existing routes.
- Remove the VM without deleting credentials unless explicitly requested.
- Run the full flake and CLI test suite successfully.

## 18. Later production path

Production promotion is intentionally separate from sandbox lifecycle.

A later workflow may inspect or export a project's deployment metadata and
produce one of:

- a NixOS service module;
- a static site derivation;
- an OCI image;
- another dedicated deployable artifact.

Caddy can then point the hostname at that durable service instead of the
development VM. No production implementation is part of the initial
CLI-first milestone.
