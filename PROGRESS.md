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
- 🟡 Tap-on-bridge networking + nftables egress allowlist (host module + smoke/agent example configs build; runtime test pending)
- ⬜ End-to-end boot test of smoke VM on a real KVM host (current verification is eval/build only)
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

2. 🟡 M2-pre: local dry-run launcher slice
   - ✅ Scaffolded `launcher/` as a Phoenix LiveView app.
   - ✅ Added SQLite schema for `sandboxes`, `agent_credentials`, and `happy_sessions`.
   - ✅ Added a read-only agent registry for `claude-code` and `codex`.
   - ✅ Built a create-sandbox form for repo URL, branch, agent, and staged credential path.
   - ✅ Persisted sandbox records and rendered the intended VM config/spec without starting systemd or microvms.
   - ✅ Added a dashboard/detail flow showing sandbox records, selected agent, generated Happy session name, and rendered VM parameters.
   - ✅ Added `devShells.x86_64-linux.launcher`, repo-local Hex/Mix caches, `checks.x86_64-linux.launcher-syntax`, `mix.lock`, and a passing `mix test` run.
   - ✅ Added Rodney/Chromium as the frontend smoke-test path and ran it against the dry-run dashboard/create/detail flow.
   - 🟡 Release packaging and future NixOS module exposure are still pending.

3. ⬜ First real NixOS/KVM deployment
   - Deploy the example host config to a real KVM-capable NixOS machine.
   - Verify `br-sandboxes`, TAP attachment, DHCP/DNS, NAT, and nftables egress behavior from inside the guest.
   - Boot the smoke VM against the curated store and confirm the guest sees only the curated `/nix/store`.
   - Verify tmpfs scratch mounts and run Node-based tooling enough to catch `O_TMPFILE` regressions.
   - Runtime-test the Claude read-only token env file mount with a real staged credential.
   - Runtime-test the Codex writable `auth.json` mount and token refresh behavior.
   - Update M1 partial items based on what actually works on the host.

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
- Current workspace has no `/dev/kvm`, so boot/runtime credential demos remain pending even though eval/build checks pass.
- qcow2 fork smoke demo succeeded under `/tmp/agent-sandcastle-qcow2.x2TBVN`: `qemu-img create -f qcow2 -F qcow2 -b base.qcow2 child.qcow2`, and `qemu-img info --output=json` reported `"backing-filename-format": "qcow2"`.
- Added `nixosConfigurations.example-agent-host` plus downstream `examples/flake.nix#nixosConfigurations.agent-demo-host` for hand-written Claude/Codex sandbox examples. Dummy credential staging paths live under `/var/lib/agent-sandcastle/example-credentials`.
- Verified `nix flake check --no-build` and `nix build --no-link .#checks.x86_64-linux.example-host-toplevel .#checks.x86_64-linux.example-agent-host-toplevel`.
- Added the initial Phoenix LiveView dry-run launcher scaffold under `launcher/`, with SQLite migrations, Ecto schemas/context, agent registry, create/dashboard/detail LiveViews, and dry-run VM spec rendering.
- Installed Hex/Rebar into ignored repo-local caches, fetched launcher dependencies, committed `launcher/mix.lock`, and verified `mix format --check-formatted` plus `mix test`.
- Verified launcher syntax with `nix build --no-link .#checks.x86_64-linux.launcher-syntax`.
- Used `rodney --help`, then Rodney against headless Chromium to test the launcher UI. Covered dashboard load, LiveView connection, `/sandboxes/new`, sequential Codex form entry, submit, detail-page rendered `mkSandbox` spec, dashboard row rendering, desktop/mobile no-horizontal-overflow assertions, accessibility lookup for "Rendered VM Spec", and screenshots under ignored `.cache/`.
- Rodney caught useful runtime gaps that unit tests missed: missing `Jason`, too-short dev/test `secret_key_base`, missing LiveView client JS for `phx-submit`, missing `inotify-tools` for LiveReload, and a LiveView testing pattern issue where parallel field input can race validation patches.
