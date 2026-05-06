# Progress

Tracking against PLAN.md §14 milestones. ✅ done · 🟡 partial · ⬜ not started.

## M0 — Foundations
- ✅ Flake scaffolding (nixpkgs, microvm.nix, `numtide/llm-agents.nix`)
- ✅ `nix/sandbox-store.nix` populates the curated chroot store via `nix copy --to "local?root=…"` (oneshot, ordered before `microvms.target`)
- ✅ `examples/flake.nix` exists; `nix build .#nixosConfigurations.example-host.config.system.build.toplevel` succeeds
- ✅ LICENSE, README

## M1 — Headless sandbox
- ✅ `mkSandbox` exposes a per-VM module
- ✅ Curated store mounted at `/nix/store` (virtiofsd runs in `PrivateMounts=yes` + `BindReadOnlyPaths=<curated>:/nix/store`; host's main `/nix/store` is invisible to the guest)
- ✅ tmpfs overlays for `/tmp`, `/var/tmp`, `/home/dev/.cache`
- ✅ Tap-on-bridge networking + nftables egress allowlist (runtime-validated on `foundry`)
- ✅ End-to-end boot test of smoke VM on a real KVM host (`foundry`)
- 🟡 Per-sandbox Claude `CLAUDE_CODE_OAUTH_TOKEN` (RO) demo (RO secrets share + env-file wiring build-verified; real token runtime test pending)
- 🟡 Per-sandbox Codex `auth.json` (RW + persist-back-on-stop) demo (RW auth share + guest symlink build-verified; persist-back + runtime refresh test pending)
- ✅ Manual qcow2 `-F qcow2` backing-file fork demo

## M2 — Launcher MVP — 🟡 dry-run scaffold started
## M3 — Forking + devenv UX — ⬜ not started
## M4 — Happy relay module + end-to-end — ⬜ not started

## Next todo order
1. ✅ Local hardening before another NixOS deploy
   - ✅ Added `checks.x86_64-linux.example-host-toplevel` so `nix flake check` builds the host networking/nftables config, not just the standalone smoke runner.
   - ✅ Added `LICENSE` and a minimal `README.md` to close the remaining M0 documentation gap.
   - ✅ Added eval-checkable hand-written Claude/Codex example configs with dummy staged credential paths.
   - ✅ Tightened docs/comments around current egress allowlist limits: hostname-to-IP resolution only, no wildcard/SNI enforcement yet, runtime validation still required.

2. ✅ M2-pre: local dry-run launcher slice
   - ✅ Scaffolded `launcher/` as a Phoenix LiveView app.
   - ✅ Added SQLite schema for `sandboxes`, `agent_credentials`, and `happy_sessions`.
   - ✅ Added a read-only agent registry for `claude-code` and `codex`.
   - ✅ Built a create-sandbox form for repo URL, branch, agent, and staged credential path.
   - ✅ Persisted sandbox records and rendered the intended VM config/spec without starting systemd or microvms.
   - ✅ Added a dashboard/detail flow showing sandbox records, selected agent, generated Happy session name, and rendered VM parameters.
   - ✅ Added `devShells.x86_64-linux.launcher`, repo-local Hex/Mix caches, `checks.x86_64-linux.launcher-syntax`, `mix.lock`, and a passing `mix test` run.
   - ✅ Added Rodney/Chromium as the frontend smoke-test path and ran it against the dry-run dashboard/create/detail flow.
   - ✅ Added a `mix release` config plus an `AgentSandcastleLauncher.Release.migrate/0` helper so the systemd unit can reconcile the SQLite schema before serving traffic. `runtime.exs` flips the endpoint to `server: true` only when `PHX_SERVER=true`, and accepts `PHX_HTTP_IP` for non-loopback binds.
   - ✅ Packaged the release through `pkgs.beamPackages.mixRelease` in `nix/launcher.nix` (with `ELIXIR_MAKE_FORCE_BUILD=true` and a writable `XDG_CACHE_HOME` so exqlite's NIF compiles in the sandbox). Exposed it as `packages.x86_64-linux.launcher` and `checks.x86_64-linux.launcher-release`.
   - ✅ Added `nixosModules.launcher` (`nix/launcher-module.nix`) with `services.agent-sandcastle.launcher` options for host/port/bind-address, an `EnvironmentFile=` for `SECRET_KEY_BASE`/`RELEASE_COOKIE`, automatic migrations via `ExecStartPre`, and a hardened systemd service with `StateDirectory=agent-sandcastle`. Wired into a downstream `example-launcher-host` config plus `checks.x86_64-linux.example-launcher-host-toplevel`.

3. 🟡 First real NixOS/KVM deployment
   - ✅ Deployed the downstream `foundry` host config with a local `agent-sandcastle` override.
   - ✅ Verified `br-sandboxes`, TAP attachment, DHCP/DNS, NAT, and nftables egress behavior from inside the guest.
   - ✅ Booted the smoke VM against the curated store and confirmed the guest sees only the curated `/nix/store`.
   - ✅ Added `nodejs` to the sandbox base image and Happy service `PATH`; verified Node/npm plus `O_TMPFILE` on `/tmp`, `/var/tmp`, and `/home/dev/.cache`.
   - ⬜ Runtime-test the Claude read-only token env file mount with a real staged credential.
   - ⬜ Runtime-test the Codex writable `auth.json` mount and token refresh behavior.
   - ✅ Updated M1 partial items based on what actually works on the host.

4. ⬜ M2 host adapter after substrate validation
   - Replace launcher `dry_run` lifecycle actions with a narrow host adapter for rendering VM definitions and starting/stopping systemd units.
   - Add systemd/journald status reads for the launcher dashboard.
   - Add per-sandbox secret staging integration for deploy keys and agent credentials.
   - Add Codex `auth.json` persist-back-on-stop.
   - Add GitLab service-account OAuth and deploy-key provisioning only after the VM lifecycle path is stable.

5. ⬜ Later M3/M4 work
   - Implement qcow2 fork action with backing-chain tracking and flatten policy.
   - Add devenv detection/template UX.
   - Add deploy-key rotation and branch-protection helper.
   - Add the Happy relay module and run the full mobile end-to-end flow.

## Notes & deviations from PLAN.md
- Happy/Claude/Codex come from `numtide/llm-agents.nix`, not a vendored `slopus/happy` submodule (PLAN §10's preferred path).
- `closureRoots` for the curated store must include `microvm.declaredRunner` alongside the VM toplevel — `virtiofsd-run` loads supervisord/virtiofsd/bash through the namespaced `/nix/store`, so a small set of host-runner deps end up readable from the guest's `/nix/store`. Acceptable: they're inert in the guest (no `/dev/kvm`, etc.).
- Standalone smoke VM (`nix run .#sandbox-smoke`) keeps `useCuratedStore = false` and falls back to microvm.nix's per-VM storeDisk. Curated-store deduplication is a host-config-level optimization.
- `nix/sandbox-network.nix` now provides the host bridge, DHCP/DNS, NAT, and nftables egress allowlist module. The example host opts its smoke VM into TAP networking; standalone `sandbox-smoke` keeps QEMU user networking so `sshHostPort` still works without host bridge setup.
- Current local workspace has no `/dev/kvm`; `foundry` is now the runtime validation target for KVM boot tests.
- qcow2 fork smoke demo succeeded under `/tmp/agent-sandcastle-qcow2.x2TBVN`: `qemu-img create -f qcow2 -F qcow2 -b base.qcow2 child.qcow2`, and `qemu-img info --output=json` reported `"backing-filename-format": "qcow2"`.
- Added `nixosConfigurations.example-agent-host` plus downstream `examples/flake.nix#nixosConfigurations.agent-demo-host` for hand-written Claude/Codex sandbox examples. Dummy credential staging paths live under `/var/lib/agent-sandcastle/example-credentials`.
- Verified `nix flake check --no-build` and `nix build --no-link .#checks.x86_64-linux.example-host-toplevel .#checks.x86_64-linux.example-agent-host-toplevel`.
- Added the initial Phoenix LiveView dry-run launcher scaffold under `launcher/`, with SQLite migrations, Ecto schemas/context, agent registry, create/dashboard/detail LiveViews, and dry-run VM spec rendering.
- Installed Hex/Rebar into ignored repo-local caches, fetched launcher dependencies, committed `launcher/mix.lock`, and verified `mix format --check-formatted` plus `mix test`.
- Verified launcher syntax with `nix build --no-link .#checks.x86_64-linux.launcher-syntax`.
- Confirmed the `mix release` artifact built through `pkgs.beamPackages.mixRelease` runs `AgentSandcastleLauncher.Release.migrate()` against an ephemeral SQLite path (53 KiB DB created with all migrations applied) and verified the resulting NixOS host config builds via `nix build --no-link "path:$PWD#checks.x86_64-linux.example-launcher-host-toplevel"`.
- `fetchMixDeps` hash currently `sha256-u47tIYiqTU2UAn4WlQrrNcOBi7vFVo9Qh8e0f59Jlxw=`; refresh it whenever `launcher/mix.lock` changes.
- Used `rodney --help`, then Rodney against headless Chromium to test the launcher UI. Covered dashboard load, LiveView connection, `/sandboxes/new`, sequential Codex form entry, submit, detail-page rendered `mkSandbox` spec, dashboard row rendering, desktop/mobile no-horizontal-overflow assertions, accessibility lookup for "Rendered VM Spec", and screenshots under ignored `.cache/`.
- Rodney caught useful runtime gaps that unit tests missed: missing `Jason`, too-short dev/test `secret_key_base`, missing LiveView client JS for `phx-submit`, missing `inotify-tools` for LiveReload, and a LiveView testing pattern issue where parallel field input can race validation patches.
- First real KVM smoke deployment on `foundry` succeeded with local downstream wiring that imports `nixosModules.host` and defines a non-autostart `sandcastle-smoke` microVM. The runtime fixes from that pass were: scripted bridge/dnsmasq networking instead of enabling host-wide `systemd-networkd`, explicit TAP attachment after microvm TAP creation, `mkSandbox` CPU/memory values that downstream hosts can actually override, and allowlist refresh using `pkgs.getent` on `PATH`.
- Foundry runtime observations: `br-sandboxes` uses `10.88.0.1/24`; dnsmasq leased `10.88.0.176` to `sandcastle-smoke`; QEMU launched with `-enable-kvm`; `microvm-virtiofsd@sandcastle-smoke` served `/nix/store` from the curated chroot via the `agent-sandcastle-curated-store` tag; the guest saw its own toplevel in `/nix/store` and did not see the foundry host toplevel.
- Guest smoke checks after adding `nodejs`: `/nix/store` is `virtiofs`, `/tmp`, `/var/tmp`, and `/home/dev/.cache` are `tmpfs`, Node `v22.22.2` and npm `10.9.7` are on `PATH`, and a Node `O_TMPFILE` probe succeeds on all three scratch mounts.
- Egress smoke checks from the guest: `https://api.openai.com` connects through the dynamic nftables allowlist (`curl` returned HTTP 421), while `https://example.com` is rejected (`curl` exit 7). The dynamic IPv6 set currently includes some IPv4-mapped `::ffff:*` results from `getent ahostsv6`; harmless in this smoke test, but worth filtering later for tidier nft state.
