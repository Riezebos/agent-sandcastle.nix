# Progress

Tracking against PLAN.md §14 milestones. ✅ done · 🟡 partial · ⬜ not started.

## M0 — Foundations
- ✅ Flake scaffolding (nixpkgs, microvm.nix, `numtide/llm-agents.nix`)
- ✅ `nix/sandbox-store.nix` populates the curated chroot store via `nix copy --to "local?root=…"` (oneshot, ordered before `microvms.target`)
- ✅ `examples/flake.nix` exists; `nix build .#nixosConfigurations.example-host.config.system.build.toplevel` succeeds
- ⬜ LICENSE, README (deferred — not blocking)

## M1 — Headless sandbox
- ✅ `mkSandbox` exposes a per-VM module
- ✅ Curated store mounted at `/nix/store` (virtiofsd runs in `PrivateMounts=yes` + `BindReadOnlyPaths=<curated>:/nix/store`; host's main `/nix/store` is invisible to the guest)
- ⬜ tmpfs overlays for `/tmp`, `/var/tmp`, `/home/dev/.cache` (next)
- ⬜ Tap-on-bridge networking + nftables egress allowlist
- ⬜ End-to-end boot test of smoke VM on a real KVM host (current verification is eval/build only)
- ⬜ Per-sandbox Claude `CLAUDE_CODE_OAUTH_TOKEN` (RO) demo
- ⬜ Per-sandbox Codex `auth.json` (RW + persist-back-on-stop) demo
- ⬜ Manual qcow2 `-F qcow2` backing-file fork demo

## M2 — Launcher MVP — ⬜ not started
## M3 — Forking + devenv UX — ⬜ not started
## M4 — Happy relay module + end-to-end — ⬜ not started

## Notes & deviations from PLAN.md
- Happy/Claude/Codex come from `numtide/llm-agents.nix`, not a vendored `slopus/happy` submodule (PLAN §10's preferred path).
- `closureRoots` for the curated store must include `microvm.declaredRunner` alongside the VM toplevel — `virtiofsd-run` loads supervisord/virtiofsd/bash through the namespaced `/nix/store`, so a small set of host-runner deps end up readable from the guest's `/nix/store`. Acceptable: they're inert in the guest (no `/dev/kvm`, etc.).
- Standalone smoke VM (`nix run .#sandbox-smoke`) keeps `useCuratedStore = false` and falls back to microvm.nix's per-VM storeDisk. Curated-store deduplication is a host-config-level optimization.
