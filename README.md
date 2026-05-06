# agent-sandcastle

Self-hosted, isolated coding-agent sandboxes for NixOS hosts. The current
prototype composes `microvm.nix` with agent packages from
`numtide/llm-agents.nix` to run Claude Code or Codex inside per-sandbox VMs.

## Status

This repository is still pre-MVP. The NixOS modules evaluate and build locally,
but the TAP bridge, nftables egress filtering, credential mounts, and microVM
boot path still need runtime validation on a KVM-capable NixOS host.

Implemented so far:

- A sandbox base image with Claude Code, Codex, Happy, Git, SSH, and scratch
  tmpfs mounts for `/tmp`, `/var/tmp`, and `/home/dev/.cache`.
- `lib.mkSandbox`, a parameterized microVM template with optional TAP
  networking, curated-store mounting, Claude token mounting, and writable Codex
  `auth.json` mounting.
- `nixosModules.sandboxStore`, which builds a curated chroot Nix store and
  serves it through a private `virtiofsd` mount namespace so guests do not see
  the host's main `/nix/store`.
- `nixosModules.sandboxNetwork`, which creates the sandbox bridge, DHCP/DNS,
  NAT, and an IP-based nftables egress allowlist.
- Eval/build examples for a smoke VM and dummy Claude/Codex agent sandboxes.
- A Phoenix LiveView launcher scaffold in `launcher/` that stores dry-run
  sandbox records in SQLite and renders intended VM specs without lifecycle
  side effects.

## Quick Checks

```sh
nix flake check
nix build .#nixosConfigurations.example-host.config.system.build.toplevel
nix build .#nixosConfigurations.example-agent-host.config.system.build.toplevel
nix build .#checks.x86_64-linux.launcher-syntax
```

The standalone smoke runner is available as:

```sh
nix run .#sandbox-smoke
```

That runner uses QEMU user networking and does not exercise the host bridge or
curated store. Runtime networking and credential behavior must be tested through
a NixOS host configuration.

## Examples

`examples/flake.nix` contains two downstream host configurations:

- `stub-host`: one TAP-backed smoke VM using the curated store.
- `agent-demo-host`: hand-written Claude and Codex sandboxes with dummy staged
  credential paths under `/var/lib/agent-sandcastle/example-credentials`.

For the Claude demo, stage an environment file like:

```sh
/var/lib/agent-sandcastle/example-credentials/claude-demo/claude.env
```

with `CLAUDE_CODE_OAUTH_TOKEN=...`. For the Codex demo, stage:

```sh
/var/lib/agent-sandcastle/example-credentials/codex-demo/auth.json
```

The paths are intentionally dummy defaults so the examples can evaluate and
build without local secrets.

## Launcher Dry Run

The launcher scaffold is under `launcher/`. Use the reproducible shell for the
Beam toolchain:

```sh
nix develop .#launcher
cd launcher
mix setup
mix phx.server
```

Run `nix develop .#launcher` from the repository root. The shell keeps Hex,
Mix, and native dependency caches in ignored repo-local directories and provides
Chromium for frontend smoke tests. Rodney session state is kept under ignored
`.rodney/`; Rodney's bundled browser downloader may still use its own cache
unless you start the Nix-provided Chromium manually and connect to it. The
current launcher mode persists records and renders the intended `mkSandbox`
config only. It does not call systemd, write microVM definitions, stage real
secrets, or start VMs.

For browser-level checks, use Rodney from the repository root against the
running Phoenix server:

```sh
rodney start --local
rodney open http://127.0.0.1:4000/
rodney assert 'document.querySelector("[data-phx-main]").classList.contains("phx-connected")'
```

## Networking Note

The current egress allowlist resolves exact hostnames into nftables IPv4/IPv6
sets and filters by destination IP. It does not enforce wildcard domains, DNS
names, TLS SNI, or HTTP Host headers at packet time. Treat it as a local
hardening prototype until it has been tested on a real KVM host.

## License

Apache-2.0. See `LICENSE`.
