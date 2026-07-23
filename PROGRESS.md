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
- ✅ Launcher security boundary: opaque credential UUIDs, path-free rendered Nix
  functions, Authentik username plus `sandbox-admins` authorization, audited
  dry-run creation, and hardened loopback-only Phoenix service, committed and
  pushed as `2648bf1`
- ✅ Real x86_64 Linux launcher dependency hash derived and committed; launcher
  release, example host toplevel, and full flake checks pass on Linux
- ⬜ Socket-activated root lifecycle broker
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
   - ✅ Built the initial create-sandbox form for repo URL, branch, agent, and a
     staged credential path; the later security-boundary pass removed that path
     and replaced it with a server-generated opaque credential UUID.
   - ✅ Persisted sandbox records and rendered the intended VM config/spec without starting systemd or microvms.
   - ✅ Added a dashboard/detail flow showing sandbox records, selected agent, generated Happy session name, and rendered VM parameters.
   - ✅ Added `devShells.x86_64-linux.launcher`, repo-local Hex/Mix caches, `checks.x86_64-linux.launcher-syntax`, `mix.lock`, and a passing `mix test` run.
   - ✅ Added Rodney/Chromium as the frontend smoke-test path and ran it against the dry-run dashboard/create/detail flow.
   - ✅ Added a `mix release` config plus an `AgentSandcastleLauncher.Release.migrate/0` helper so the systemd unit can reconcile the SQLite schema before serving traffic. `runtime.exs` flips the endpoint to `server: true` only when `PHX_SERVER=true`, and accepts `PHX_HTTP_IP` for non-loopback binds.
   - ✅ Packaged the release through `pkgs.beamPackages.mixRelease` in `nix/launcher.nix` (with `ELIXIR_MAKE_FORCE_BUILD=true` and a writable `XDG_CACHE_HOME` so exqlite's NIF compiles in the sandbox). Exposed it as `packages.x86_64-linux.launcher` and `checks.x86_64-linux.launcher-release`.
   - ✅ Added `nixosModules.launcher` (`nix/launcher-module.nix`) with `services.agent-sandcastle.launcher` options for host/port/bind-address, an `EnvironmentFile=` for `SECRET_KEY_BASE`/`RELEASE_COOKIE`, automatic migrations via `ExecStartPre`, and a hardened systemd service with `StateDirectory=agent-sandcastle`. Wired into a downstream `example-launcher-host` config plus `checks.x86_64-linux.example-launcher-host-toplevel`.
   - ✅ Removed the free-form credential path from the request/UI. Dry runs now generate opaque UUID credential IDs, and the renderer emits a function whose `credentialSource` must be supplied by the future trusted broker.
   - ✅ Added application-level Authentik username/group enforcement, `sandbox-admins` gating, create-action audit attribution, path/escaping/Codex coverage, and a LiveView create-flow test.
   - ✅ Tightened the Phoenix unit for its still-dry-run scope with `NoNewPrivileges`, `ProtectSystem=strict`, a private device view, and a state-directory-only write boundary.
   - ✅ Refreshed the locked launcher dependencies to releases with no `mix hex.audit` advisories.

3. 🟡 First real NixOS/KVM and launcher deployment
   - ✅ Deployed the downstream `foundry` host config with a local `agent-sandcastle` override.
   - ✅ Verified `br-sandboxes`, TAP attachment, DHCP/DNS, NAT, and nftables egress behavior from inside the guest.
   - ✅ Booted the smoke VM against the curated store and confirmed the guest sees only the curated `/nix/store`.
   - ✅ Added `nodejs` to the sandbox base image and Happy service `PATH`; verified Node/npm plus `O_TMPFILE` on `/tmp`, `/var/tmp`, and `/home/dev/.cache`.
   - ✅ Derived the real Linux Mix dependency hash
     `sha256-Hjluglh8h1zDt1UCOARgXiasEAIDUNr7nxX94QxsZ2U=` and pushed upstream
     commit `414b60b9647dbaa68ce97b121dd07be873ef2438`.
   - ✅ On x86_64 Linux, passed launcher formatting, 10 tests with zero
     failures, `mix hex.audit`, the launcher build, the example launcher host
     toplevel build, and `nix flake check`.
   - ✅ Updated the downstream lock and Authentik/Caddy boundary comment and
     pushed `07b28baae760ee0655e7d519ee8951ba92bca7e0`.
   - ✅ Downloaded Foundry VTT Linux 14.359, verified SHA-256
     `c3e535264274bb9092234aedc7b1e945b4767ca62f9b9da1e088a19beabee9b5`,
     and seeded it into the local Nix store so the full downstream build could
     complete.
   - 🟡 Downstream `main` deployment was triggered; final activation and
     post-deploy service/migration/HTTP verification are being tracked
     separately and must not be inferred from the successful build.
   - ⬜ Runtime-test the Claude read-only token env file mount with a real staged credential.
   - ⬜ Runtime-test the Codex writable `auth.json` mount and token refresh behavior.
   - ✅ Updated M1 partial items based on what actually works on the host.

4. ⬜ M2 host adapter after substrate validation
   - Implement a small Go broker. Go is the selected balance for a narrow,
     I/O-heavy privileged boundary: a compact static binary, straightforward
     Unix sockets and peer credentials, memory safety, and low deployment
     overhead. Rust remains a defensible higher-complexity alternative; Elixir,
     Python, shell, and C are not preferred inside this root boundary.
   - Let systemd own a `root:agent-sandcastle` mode `0660` Unix stream socket
     and start one hardened broker process per connection (`Accept=yes`). No
     always-running broker daemon or job-directory watcher is needed at the
     current scale.
   - Begin with `ping`, protocol framing, peer authentication, limits, and
     credential-resolution tests before exposing mutations.
   - Use versioned strict JSON, reject unknown fields, cap request/response
     sizes, set deadlines, and accept only fixed typed operations. Never accept
     an arbitrary command, unit name, path, Nix expression, environment
     variable, or systemd property.
   - Resolve opaque credential IDs only inside the broker beneath a fixed
     root-owned staging root. Reject traversal, symlinks, unexpected
     ownership/mode/type, malformed UUIDs, and mismatched credential shapes.
   - Derive all unit names and filesystem paths from canonical sandbox UUIDs.
     Add root-owned per-sandbox locks, idempotency keys, and audit correlation
     IDs. Authenticate with Unix peer credentials in addition to socket mode.
   - Add fixed create/start/stop/status/persist-Codex-auth operations. Batch
     status requests so LiveView polling does not spawn one root process per
     table row.
   - Prove Codex failure ordering: VM stopped first, refreshed auth validated
     and persisted second, success reported last. Persistence failure must
     produce a failed/quarantined state rather than stale-auth restart.
   - Do not grant Phoenix direct systemd, KVM, sudo, credential-path, or
     microVM filesystem access.
   - Add systemd/journald status reads for the launcher dashboard.
   - Add per-sandbox secret staging integration for deploy keys and agent credentials.
   - Add GitLab service-account OAuth and deploy-key provisioning only after the VM lifecycle path is stable.

5. ⬜ Shared-host operational guardrails
   - Keep the initial Foundry deployment to trusted `sandbox-admins`, trusted or
     private repositories, and at most two simultaneously active sandboxes.
   - Put all Sandcastle services/VMs in a dedicated systemd slice with aggregate
     CPU, memory, process, file-descriptor, log, disk-growth, and I/O limits.
     Reserve capacity for Foundry VTT, Authentik, PostgreSQL, monitoring, and
     backups; tune actual values from runtime measurements.
   - Add unconditional nftables denies from guests to the host, loopback, other
     sandboxes, LAN/RFC1918, link-local, metadata, and management services.
     Keep sandbox inbound ports closed by default.
   - Exclude credential staging from backups and logs. Add a launcher/broker
     kill switch that prevents new starts without disrupting the other Foundry
     services.
   - Keep launcher, broker, credentials, VM state/store, and sandbox networking
     relocatable as one Sandcastle plane. Move the whole plane to a dedicated
     KVM host when users become less trusted, external PRs are routine, more
     than two or three VMs run concurrently, Foundry latency appears, or
     code/credentials become materially valuable.
   - If Authentik identity crosses hosts later, protect the proxy channel with a
     private authenticated transport or validate tokens directly; do not extend
     the current loopback trusted-header assumption over an ordinary network.

6. ⬜ Later M3/M4 work
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
- `fetchMixDeps` hash currently
  `sha256-Hjluglh8h1zDt1UCOARgXiasEAIDUNr7nxX94QxsZ2U=`; refresh it whenever
  `launcher/mix.lock` changes.
- Used `rodney --help`, then Rodney against headless Chromium to test the launcher UI. Covered dashboard load, LiveView connection, `/sandboxes/new`, sequential Codex form entry, submit, detail-page rendered `mkSandbox` spec, dashboard row rendering, desktop/mobile no-horizontal-overflow assertions, accessibility lookup for "Rendered VM Spec", and screenshots under ignored `.cache/`.
- Rodney caught useful runtime gaps that unit tests missed: missing `Jason`, too-short dev/test `secret_key_base`, missing LiveView client JS for `phx-submit`, missing `inotify-tools` for LiveReload, and a LiveView testing pattern issue where parallel field input can race validation patches.
- First real KVM smoke deployment on `foundry` succeeded with local downstream wiring that imports `nixosModules.host` and defines a non-autostart `sandcastle-smoke` microVM. The runtime fixes from that pass were: scripted bridge/dnsmasq networking instead of enabling host-wide `systemd-networkd`, explicit TAP attachment after microvm TAP creation, `mkSandbox` CPU/memory values that downstream hosts can actually override, and allowlist refresh using `pkgs.getent` on `PATH`.
- Foundry runtime observations: `br-sandboxes` uses `10.88.0.1/24`; dnsmasq leased `10.88.0.176` to `sandcastle-smoke`; QEMU launched with `-enable-kvm`; `microvm-virtiofsd@sandcastle-smoke` served `/nix/store` from the curated chroot via the `agent-sandcastle-curated-store` tag; the guest saw its own toplevel in `/nix/store` and did not see the foundry host toplevel.
- Guest smoke checks after adding `nodejs`: `/nix/store` is `virtiofs`, `/tmp`, `/var/tmp`, and `/home/dev/.cache` are `tmpfs`, Node `v22.22.2` and npm `10.9.7` are on `PATH`, and a Node `O_TMPFILE` probe succeeds on all three scratch mounts.
- Egress smoke checks from the guest: `https://api.openai.com` connects through the dynamic nftables allowlist (`curl` returned HTTP 421), while `https://example.com` is rejected (`curl` exit 7). The dynamic IPv6 set currently includes some IPv4-mapped `::ffff:*` results from `getent ahostsv6`; harmless in this smoke test, but worth filtering later for tidier nft state.
- Architecture review against Coder, GitHub/GitLab self-hosted runners,
  microvm.nix, Firecracker production guidance, and systemd socket activation
  supports the current phased approach: co-locate the small trusted prototype,
  keep execution ephemeral/per-user and network-segmented, preserve a clean
  control-plane/worker boundary, and move the complete Sandcastle plane when
  the trust or load triggers above are reached.
- The number of services on Foundry is not itself the limiting concern. Caddy,
  Authentik, PostgreSQL, monitoring, backups, and CrowdSec form a coherent
  hosting platform. Sandcastle is different because it runs user-controlled
  code; host-kernel/hypervisor escape and resource contention are the reasons
  for the explicit limits and future physical separation.
