# Progress

Tracking the CLI-first milestones in `PLAN.md`.
✅ done · 🟡 reusable but changing · ⬜ not started

The earlier Phoenix/Authentik/Happy control-plane plan has been retired. Work
completed for that design is recorded below as historical context, but it is
not part of the remaining implementation path.

## Current status

- ✅ The MicroVM substrate has been evaluated, built, and booted on Foundry.
- ✅ TAP networking, DNS, NAT, KVM, virtiofs, tmpfs scratch paths, and basic
  egress filtering have been runtime-tested.
- ✅ `mkSandbox` and the guest base provide a useful starting point.
- ✅ Claude Code, Codex, Node.js, Git, SSH, and common shell tools are already
  packaged in the guest closure.
- ✅ The `sandcastle` CLI, its JSON schema, state model, and the JSON-to-runner
  builder exist and are exercised by 90 unit tests plus `nix flake check`.
- ✅ A runtime-created sandbox builds end to end: a spec allocated by the CLI
  produces a MicroVM runner with a per-VM store image, a VSOCK CID, a static
  address, and the requested packages, installed through `current` and a Nix
  GC root.
- 🟡 The legacy declarative host integration and curated union store are still
  present; the CLI host module does not use them.
- 🟡 The current network module works but its hostname/IP egress allowlist will
  be replaced by public-internet egress with private/internal blocking.
- ✅ The CLI-managed lifecycle exists: `create`, `status`, `start`, `stop`,
  `restart`, `rebuild`, `logs`, `ssh`, and `delete`.
- ✅ VSOCK SSH into a guest as `dev` has been runtime-verified, including host
  key persistence across a reboot.
- ⬜ No integrated fork operation exists yet.
- ⬜ No dynamic Caddy route management exists yet.
- ⬜ Phoenix, Happy, and their downstream deployment have not yet been removed.

## M0 — Reusable substrate

- ✅ Flake scaffolding with nixpkgs, `microvm.nix`, and
  `numtide/llm-agents.nix`.
- ✅ `lib.mkSandbox` produces a parameterized MicroVM NixOS module.
- ✅ Guest base with unprivileged `dev`, OpenSSH, Claude Code, Codex, Node.js,
  Happy, Git, curl, jq, ripgrep, and common shell tools.
- ✅ Persistent `/home/dev` raw volume definition.
- ✅ tmpfs mounts for `/tmp`, `/var/tmp`, and `/home/dev/.cache`.
- ✅ TAP bridge, dnsmasq, NAT, and nftables integration.
- ✅ KVM smoke VM booted successfully on Foundry.
- ✅ Guest saw only its curated store rather than the host's full Nix store.
- ✅ Node/npm and scratch-filesystem behavior validated inside the guest.
- ✅ Allowed and rejected egress paths validated from the guest.
- ✅ Example host and agent configurations build.

M0 is complete. Some implementation choices are intentionally replaced in
later milestones, but their runtime validation remains useful.

## M1 — CLI and state model

- ✅ Add a Python standard-library `sandcastle` application.
- ✅ Package it as `packages.x86_64-linux.sandcastle`.
- ✅ Expose it as `apps.x86_64-linux.sandcastle`.
- ✅ Define the versioned JSON sandbox schema.
- ✅ Add strict validation for names, package attributes, ports, IPs, CIDs, and
  hostnames.
- ✅ Add `/var/lib/sandcastle` state directories through the host module.
- ✅ Set `microvm.stateDir = "/var/lib/sandcastle/vms"`.
- ✅ Add global allocation and per-sandbox locks.
- ✅ Add atomic specification and symlink updates.
- ✅ Add Nix GC-root management for installed runners.
- ✅ Build a runner from a JSON specification.
- ✅ Switch runtime-created sandboxes to MicroVM's per-VM store image.
- ✅ Add unit tests for schema migration, allocation conflicts, path
  resolution, and failed atomic operations.

M1 is complete. What exists now:

- `sandcastle/` — a standard-library Python package with `errors`, `validate`,
  `config`, `spec`, `state`, `build`, `systemd`, and `cli` modules.
- `nix/sandcastle-package.nix` — the CLI derivation. Its `checkPhase` runs the
  unit tests, so `nix flake check` fails if they do.
- `nix/guest-module.nix` — the CLI-first guest: `dev` user, VSOCK SSH, static
  address, per-VM store image, tmpfs scratch paths, no Happy.
- `nix/sandbox-builder.nix` — `lib.runnerFromSpecFile`, which the CLI evaluates
  against this flake's own store path so sandboxes are built from the same
  pinned inputs as the host.
- `nix/host-module.nix` — `services.sandcastle`, the state tree, the MicroVM
  state root, `/etc/sandcastle/config.json`, the GC-root directory, and the
  generic TAP-to-bridge attachment for runtime-created VMs.
- CLI commands so far: `list`, `show`, and `build [--install]`.

Verified locally: `nix flake check` passes (9 checks), and a CLI-allocated
`cli-smoke` spec built a runner carrying its own store image, its allocated
MAC, VSOCK CID 100, `systemd.machine_id=`, a `sc-`-prefixed TAP device, and
`nodejs`, `pnpm`, `python3`, and `uv` in the guest system path. Booting it is
still M2 work on Foundry.

Notable design decisions made during M1:

- The persisted spec holds no network topology. The CLI composes a build input
  from the spec plus the host's gateway, prefix length, and resolvers, so
  changing the bridge subnet is a rebuild rather than a rewrite of every spec.
- Runner builds use `builtins.getFlake` on the flake's store path and read the
  build input from a store path, which requires `--impure`. Nothing an
  operator typed is ever spliced into the expression as source text.
- Guests keep `type = "tap"` interfaces rather than QEMU's bridge helper, so
  QEMU's own `-sandbox on` seccomp confinement stays enabled.
- Machine identity is applied through `systemd.machine_id=` on the kernel
  command line rather than a generated `/etc/machine-id`.

## M2 — Lifecycle and VSOCK SSH

- ✅ Implement `create`.
- ✅ Implement `list` and `status` without reevaluating every sandbox.
- ✅ Implement `start`, `stop`, and `restart`.
- ✅ Implement `rebuild` with candidate-build-first activation.
- ✅ Roll back `current` after failed activation.
- ✅ Implement host-side and guest-side log access.
- ✅ Implement guarded `delete`.
- ✅ Allocate stable IPv4 addresses and MAC addresses.
- ✅ Allocate unique VSOCK CIDs and machine identities.
- ✅ Enable the guest's `microvm.vsock.ssh` support.
- ✅ Implement `sandcastle ssh <name>` as user `dev`.
- ✅ Keep per-sandbox SSH known-hosts state.
- ✅ Support opt-in SSH agent forwarding.
- ✅ Enforce the host's concurrent-VM limit before starting another sandbox.
  (Listed under M3, but `start` is the only place it belongs.)
- 🟡 Runtime-tested locally under WSL2 KVM; not yet exercised through the
  `microvm@` units on Foundry.

M2 is functionally complete. What exists now:

- `sandcastle/lifecycle.py` — `create`, `start`, `stop`, `restart`, `rebuild`,
  `delete`, and `status`, plus the create unwind and the rebuild rollback.
- `sandcastle/ssh.py` — the control key, per-sandbox known-hosts state, and
  the `ssh` argument vector for a `vsock/<cid>` destination.
- `sandcastle/systemd.py` — batched `is-active`, `systemctl show`, the
  activation readiness check, and the `journalctl` argument vector.
- CLI commands: `list`, `show`, `status`, `create`, `start`, `stop`,
  `restart`, `rebuild`, `build`, `logs`, `ssh`, `delete`.

Verified: `nix flake check` passes and the CLI unit suite is 185 tests.

### Runtime validation performed locally

WSL2 turned out to have `/dev/kvm`, `/dev/vhost-vsock`, and systemd as PID 1,
so the guest side was verified by booting a real runner rather than by
inspection. A probe sandbox built through `lib.runnerFromSpecFile` from a real
`build_input` document was booted directly, with only the TAP `-netdev`
arguments removed because no host bridge exists there. Confirmed:

- `sshd-vsock.socket` is active in the guest;
- `ssh vsock/<cid>` logs in as `dev` using only the control key;
- the guest host key lands on `identity.img` at `/var/lib/sandcastle/ssh`;
- after a full guest restart the pinned host key still matches, so
  `known-hosts` state does not have to be re-accepted;
- `journalctl` works for `dev`, which is what `logs --guest` needs;
- microvm.nix does create and format both `home.img` and `identity.img` on
  first boot.

Two real bugs were found this way rather than by reading code:

1. `microvm.vsock.ssh.enable` alone did **not** give the guest a VSOCK SSH
   listener. `systemd-ssh-generator` only writes `sshd-vsock.socket` when
   `/dev/vsock` already exists, and generators run before udev can autoload
   the virtio transport from the device's modalias, so the guest silently came
   up listening only on the AF_UNIX local socket. Fixed by loading
   `vmw_vsock_virtio_transport` from the initrd.
2. `systemd.machine_id=` on the kernel command line is silently ignored for
   the all-zero ID, and systemd then falls back to the hypervisor's SMBIOS
   UUID. `validate_machine_id` now rejects the null ID so an allocated
   identity cannot be lost that way.

### Still to do on Foundry

- Deploy the CLI host and run `create`/`start`/`ssh`/`rebuild`/`delete`
  through the real `microvm@<name>.service` units.
- Confirm the generic TAP-to-bridge `ExecStartPost` attaches a runtime
  sandbox's `sc-` device.
- Confirm the `microvm` user can write `booted` in the VM directory. The
  directory is now explicitly chmodded to 0775 rather than left to root's
  umask, which would have made `microvm-set-booted@` fail.

Notable design decisions made during M2:

- Guest SSH host keys live on a separate small `identity.img` volume rather
  than on `home.img` or in the read-only system closure. That is what makes
  host-key pinning survive a reboot while still letting a fork copy the home
  disk without inheriting the parent's identity.
- The public control key is a build input, like the network parameters, not a
  spec field. Rotating it is a rebuild rather than a rewrite of every spec.
- Activation success is measured, not assumed. `microvm@.service` is
  `Type=simple` with `Restart=always` under QEMU, so `systemctl start`
  returns successfully for a guest that cannot boot; without the readiness
  check the rollback requirement would never have fired.
- `rebuild` does not stop the guest before moving `current`. microvm.nix's
  `booted` symlink still points at the old runner, so the unit's `ExecStop`
  keeps shutting the running guest down with the runner it was started from.
- Everything after `--` on the command line goes to the tool sandcastle execs,
  because argparse consumes the marker itself.

## M3 — Packages, egress, and shared-host limits

- ⬜ Define base guest packages without Happy.
- ⬜ Resolve validated nixpkgs package attribute paths from the sandbox spec.
- ⬜ Add `packages list`, `packages add`, and `packages remove`.
- ⬜ Add convenience profiles for Node, Python, Go, and Rust.
- ⬜ Runtime-test `pnpm install`.
- ⬜ Runtime-test `uv sync` and a project-local virtual environment.
- ⬜ Confirm project dependencies survive reboot.
- ⬜ Remove the exact-hostname dynamic egress allowlist.
- ⬜ Allow general public-internet egress.
- ⬜ Retain denies for host, sandbox peers, LAN, private, link-local, metadata,
  multicast, and other non-public destinations.
- ⬜ Add aggregate Sandcastle systemd slice limits.
- ✅ Add disk-space and concurrent-VM checks. (Landed with M2: `create`
  refuses when the declared disks plus headroom would not fit, and `start`
  refuses past `maxRunning`.)

## M4 — Reliable filesystem forks

- ✅ A standalone `qemu-img` backing-file experiment demonstrated qcow2
  mechanics.
- 🟡 The experiment is not integrated: the current QEMU runner declares
  sandbox volumes as raw disks, so it does not satisfy the new fork milestone.
- ⬜ Implement parent/child locking.
- ⬜ Stop and cleanly quiesce the parent.
- ⬜ Sparse-copy the raw home disk with `qemu-img convert`, and only that disk:
  leaving `identity.img` uncopied is what gives the child a fresh guest SSH
  host identity, with nothing to generate or scrub.
- ⬜ Clone the non-secret package and resource specification.
- ⬜ Allocate new IP, MAC, VSOCK, and machine identities.
- ⬜ Create an empty credential directory for the child.
- ⬜ Ensure routes are not inherited.
- ⬜ Restore the parent's prior running state.
- ⬜ Test an uncommitted file surviving the fork.
- ⬜ Test parent and child filesystem divergence.
- ⬜ Measure fork duration before considering qcow2 backing chains.

## M5 — Dynamic Caddy routes

- ✅ Wildcard `*.simonito.com` DNS is already available downstream.
- ✅ Authentik already exists on Foundry and its Caddy `forward_auth` pattern is
  known.
- ⬜ Add a Caddy import for `/var/lib/sandcastle/caddy/*.caddy`.
- ⬜ Install a harmless placeholder snippet.
- ⬜ Implement route-state validation and collision detection.
- ⬜ Implement `expose` with public mode.
- ⬜ Implement `expose` with Authentik mode.
- ⬜ Implement `routes` and `unexpose`.
- ⬜ Validate the complete Caddy configuration before reload.
- ⬜ Roll back snippet changes when validation or reload fails.
- ⬜ Verify a public development server over HTTPS.
- ⬜ Verify an Authentik-protected development server over HTTPS.
- ⬜ Verify invalid route changes do not disturb existing services.

## M6 — Cutover and cleanup

### Upstream repository

- ⬜ Remove `launcher/`.
- ⬜ Remove `nix/launcher.nix`.
- ⬜ Remove `nix/launcher-module.nix`.
- ⬜ Remove launcher packages, checks, migrations, and the Elixir dev shell.
- ⬜ Remove Phoenix/Elixir dependencies from the flake.
- ⬜ Remove Happy packages and guest service wiring.
- ⬜ Remove the curated-store runtime path after CLI VMs use per-VM stores.
- ⬜ Replace the existing examples with CLI-first examples.

### Downstream `nix` repository

- ⬜ Replace `agentSandcastleLauncher` with the CLI host feature.
- ⬜ Remove the launcher sops secret declaration.
- ⬜ Remove the `sandcastle.simonito.com` proxy to `127.0.0.1:4000`.
- ⬜ Add the dynamic sandbox Caddy import.
- ⬜ Keep Authentik available for protected sandbox routes.
- ⬜ Deploy and verify the new configuration.
- ⬜ Review the old launcher state directory before any explicit deletion.

## M7 — Documentation and release

- ⬜ Rewrite `README.md` around the real CLI.
- ⬜ Document create, rebuild, fork, expose, and guarded deletion.
- ⬜ Document that sandbox disks are not backed up by default.
- ⬜ Document recovery from a failed runner activation.
- ⬜ Add end-to-end Foundry verification instructions.
- ⬜ Pass all Nix evaluation, build, CLI unit, and smoke checks.
- ⬜ Tag the first CLI-first release.

## Immediate next steps

1. Deploy the CLI host to Foundry and run the full lifecycle through the real
   `microvm@<name>.service` units, alongside the current launcher.
2. Add package mutation (`packages list/add/remove`) and simplified egress.
3. Add aggregate systemd slice limits.
4. Add raw-disk forking.
5. Add Caddy route management. `delete` already refuses to remove a sandbox
   whose Caddy snippet carries a `# sandcastle-sandbox: <name>` marker, so M5
   must emit that marker.
6. Remove Phoenix, Happy, the launcher secret, and the curated-store path only
   after the replacement passes the acceptance checklist.

## Historical work now scheduled for removal

The following work was completed and deployed successfully, but belongs to the
retired architecture:

- Phoenix LiveView launcher with SQLite migrations.
- Authentik header and `sandbox-admins` checks.
- Opaque credential UUIDs and path-free dry-run VM rendering.
- Launcher Nix package and hardened NixOS systemd service.
- Browser and application tests.
- The proposed root lifecycle broker protocol.
- Happy session and relay planning.

This history remains in Git. It should not constrain the CLI implementation or
be kept merely because it already exists.

## Known implementation facts

- The WSL2 development machine does have `/dev/kvm`, `/dev/vhost-vsock`, and
  systemd as PID 1, so a runner can be booted and SSHed into locally. It has
  no sandbox bridge, so TAP networking, DNS, NAT, and egress still have to be
  validated on Foundry.
- The currently locked `microvm.nix` host module already provides generic
  `microvm@.service` units and VSOCK SSH support, but `microvm.vsock.ssh` on
  its own is not sufficient: see the initrd module note in M2.
- Only cloud-hypervisor sets `supportsNotifySocket`, so QEMU sandboxes are
  `Type=simple` and their start cannot report a guest that fails to boot.
- `microvm-set-booted@.service` runs as the unprivileged `microvm` user in the
  VM directory, so that directory must stay group-writable by `kvm`.
- The current QEMU runner opens declared `microvm.volumes` with
  `format=raw`; the first integrated fork implementation therefore stays raw.
  The generated `cli-smoke` runner confirms this: `home.img` is opened as
  `format=raw` relative to the VM state directory.
- microvm.nix auto-creates and formats a declared volume on first boot, but
  only when the image file does not already exist. `create` therefore does the
  free-space check and leaves image creation to the runner rather than
  pre-creating a file the runner would then refuse to format.
- Kernel interface names cap at 15 characters, so guest TAP devices are named
  `sc-` plus 11 hex characters of `sha256(name)`. That derivation exists in
  `nix/guest-module.nix` and `sandcastle/state.py` and is pinned by a test.
- Runtime-created sandboxes are not in `config.microvm.vms`, so the host
  cannot enumerate them at build time. TAP devices are attached to the bridge
  by a generic `ExecStartPost` that adopts any unattached `sc-` device.
- The curated union store requires the host configuration to know all guest
  closure roots and conflicts with runtime-created CLI sandboxes.
- A writable guest Nix store is not planned initially. Immutable package-list
  rebuilds plus project-local `uv` and `pnpm` state are the chosen model.
- The current egress allowlist works technically but is intentionally replaced
  because hostname-to-IP rules are too brittle for general development.
- Credentials and Caddy routes are separate state and are never inherited by
  forks. The guest's SSH host key is a third such piece of state: it lives on
  `identity.img`, which a fork must recreate rather than copy.
