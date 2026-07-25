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
- 🟡 The current host integration is fully declarative and uses a curated
  union store; both need adapting for runtime-created CLI sandboxes.
- 🟡 The current network module works but its hostname/IP egress allowlist will
  be replaced by public-internet egress with private/internal blocking.
- ⬜ No CLI-managed sandbox lifecycle exists yet.
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

- ⬜ Add a Python standard-library `sandcastle` application.
- ⬜ Package it as `packages.x86_64-linux.sandcastle`.
- ⬜ Expose it as `apps.x86_64-linux.sandcastle`.
- ⬜ Define the versioned JSON sandbox schema.
- ⬜ Add strict validation for names, package attributes, ports, IPs, CIDs, and
  hostnames.
- ⬜ Add `/var/lib/sandcastle` state directories through the host module.
- ⬜ Set `microvm.stateDir = "/var/lib/sandcastle/vms"`.
- ⬜ Add global allocation and per-sandbox locks.
- ⬜ Add atomic specification and symlink updates.
- ⬜ Add Nix GC-root management for installed runners.
- ⬜ Build a runner from a JSON specification.
- ⬜ Switch runtime-created sandboxes to MicroVM's per-VM store image.
- ⬜ Add unit tests for schema migration, allocation conflicts, path
  resolution, and failed atomic operations.

## M2 — Lifecycle and VSOCK SSH

- ⬜ Implement `create`.
- ⬜ Implement `list` and `status` without reevaluating every sandbox.
- ⬜ Implement `start`, `stop`, and `restart`.
- ⬜ Implement `rebuild` with candidate-build-first activation.
- ⬜ Roll back `current` after failed activation.
- ⬜ Implement host-side and guest-side log access.
- ⬜ Implement guarded `delete`.
- ⬜ Allocate stable IPv4 addresses and MAC addresses.
- ⬜ Allocate unique VSOCK CIDs and machine identities.
- ⬜ Enable the guest's `microvm.vsock.ssh` support.
- ⬜ Implement `sandcastle ssh <name>` as user `dev`.
- ⬜ Keep per-sandbox SSH known-hosts state.
- ⬜ Support opt-in SSH agent forwarding.
- ⬜ Runtime-test the full lifecycle on Foundry with `cli-smoke`.

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
- ⬜ Add disk-space and concurrent-VM checks.

## M4 — Reliable filesystem forks

- ✅ A standalone `qemu-img` backing-file experiment demonstrated qcow2
  mechanics.
- 🟡 The experiment is not integrated: the current QEMU runner declares
  sandbox volumes as raw disks, so it does not satisfy the new fork milestone.
- ⬜ Implement parent/child locking.
- ⬜ Stop and cleanly quiesce the parent.
- ⬜ Sparse-copy the raw home disk with `qemu-img convert`.
- ⬜ Clone the non-secret package and resource specification.
- ⬜ Allocate new IP, MAC, VSOCK, machine, and SSH identities.
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

1. Define the JSON schema and state-directory invariants.
2. Package a minimal CLI with `list`, validation, locking, and atomic writes.
3. Implement the JSON-to-MicroVM runner builder using per-VM store images.
4. Implement `create`, `start`, `stop`, `status`, and VSOCK `ssh`.
5. Deploy a `cli-smoke` sandbox alongside the current launcher.
6. Add package mutation and simplified egress.
7. Add raw-disk forking.
8. Add Caddy route management.
9. Remove Phoenix, Happy, the launcher secret, and the curated-store path only
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

- Local development on macOS has no `/dev/kvm`; Foundry remains the runtime
  validation host.
- The currently locked `microvm.nix` host module already provides generic
  `microvm@.service` units and VSOCK SSH support.
- The current QEMU runner opens declared `microvm.volumes` with
  `format=raw`; the first integrated fork implementation therefore stays raw.
- The curated union store requires the host configuration to know all guest
  closure roots and conflicts with runtime-created CLI sandboxes.
- A writable guest Nix store is not planned initially. Immutable package-list
  rebuilds plus project-local `uv` and `pnpm` state are the chosen model.
- The current egress allowlist works technically but is intentionally replaced
  because hostname-to-IP rules are too brittle for general development.
- Credentials and Caddy routes are separate state and are never inherited by
  forks.
