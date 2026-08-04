# agent-sandcastle

Self-hosted, isolated coding-agent sandboxes for NixOS hosts. The current
prototype composes `microvm.nix` with agent packages from
`numtide/llm-agents.nix` to run Claude Code or Codex inside per-sandbox VMs.

## Status

This repository is still pre-MVP. The NixOS modules evaluate and build locally,
but the TAP bridge, nftables egress filtering, credential mounts, and microVM
boot path still need runtime validation on a KVM-capable NixOS host.

Implemented so far:

- A `sandcastle` CLI (`sandcastle/`) with a versioned JSON sandbox schema,
  strict validation, locking, atomic state updates, allocation of addresses
  and VSOCK CIDs, Nix GC-root management, and a JSON-to-MicroVM runner
  builder. `list`, `show`, `status`, `create`, `start`, `stop`, `restart`,
  `rebuild`, `build`, `logs`, `ssh`, and `delete` are wired up; packages,
  fork, and route commands are next.
- `nixosModules.sandcastleHost`, which installs the CLI, creates the state
  directories, and points `microvm.stateDir` at them.
- `nixosModules.sandcastleGuest`, the guest module a sandbox runner is built
  from: unprivileged `dev` user, per-VM store image, VSOCK SSH, Claude Code
  and Codex, and scratch tmpfs mounts for `/tmp`, `/var/tmp`, and
  `/home/dev/.cache`.
- `nixosModules.sandboxNetwork`, which creates the sandbox bridge, DHCP/DNS,
  NAT, and an IP-based nftables egress allowlist.

The Phoenix launcher, `lib.mkSandbox`, and the curated union store have been
removed; see `PLAN.md` for the CLI-first design that replaced them.

## Quick Checks

```sh
nix flake check
nix build .#nixosConfigurations.example-cli-host.config.system.build.toplevel
nix build .#checks.x86_64-linux.sandbox-example-runner
```

The CLI's unit tests run inside its derivation, so `nix build .#sandcastle`
fails if they do. To iterate without Nix:

```sh
python3 -m unittest discover --start-directory tests --top-level-directory .
```

## CLI-First Path

`PLAN.md` describes the CLI-first design and `PROGRESS.md` tracks it. The host
side is enabled with:

```nix
{
  imports = [ agent-sandcastle.nixosModules.sandcastleHost ];
  services.sandcastle.enable = true;
}
```

That installs the `sandcastle` command, creates `/var/lib/sandcastle`, points
`microvm.stateDir` at `/var/lib/sandcastle/vms`, and writes
`/etc/sandcastle/config.json` so the CLI knows the bridge subnet and which
flake to build sandboxes from. Sandbox runners are built by evaluating
`lib.runnerFromSpecFile` against that flake, so a sandbox always uses the same
pinned nixpkgs and `microvm.nix` as the host it runs on.

Runtime-created sandboxes use `microvm.nix`'s per-VM store image, which is what
makes them possible without the host configuration knowing every guest closure
root in advance.

### Lifecycle

```sh
sudo sandcastle create my-app --packages node python
sudo sandcastle start my-app
sudo sandcastle status my-app
sudo sandcastle ssh my-app
sudo sandcastle logs my-app -f
sudo sandcastle rebuild my-app
sudo sandcastle stop my-app
sudo sandcastle delete my-app --yes
```

`create` reserves the name, address, MAC, VSOCK CID, and machine identity
first, then builds. A failure at any later step releases everything it
reserved, so a failed `create` never leaves a half-addressable sandbox behind.
Credentials a previous `delete` deliberately kept are not touched by that
unwind.

`rebuild` realises the candidate runner before it moves `current`, so a bad
package list costs a failed build rather than a broken sandbox. The replaced
runner is retained as the `previous` GC root, and if the guest does not come
back up, `current` is rolled back to it and restarted.

Because `microvm@<name>.service` is `Type=simple` with `Restart=always` under
QEMU, `systemctl start` succeeds even for a guest that cannot boot. The CLI
therefore confirms activation by watching the unit hold a single invocation in
a running state for a few seconds; `--no-wait` skips that.

### Guest access

`sandcastle ssh` connects over AF_VSOCK, so no guest SSH port is forwarded or
opened publicly:

```sh
sudo sandcastle ssh my-app                       # interactive shell as dev
sudo sandcastle ssh my-app tmux attach           # run a command in the guest
sudo sandcastle ssh my-app -- -L 3000:localhost:3000   # options for ssh itself
sudo --preserve-env=SSH_AUTH_SOCK sandcastle ssh -A my-app
```

Everything after `--` goes to `ssh`; anything else after the name is a command
for the guest. Agent forwarding is opt-in and needs `SSH_AUTH_SOCK` to survive
`sudo`.

Two separate pieces of key material are involved:

- one **control key** per installation, at
  `/var/lib/sandcastle/ssh/control_ed25519`. It is created on first use and its
  public half is a *build input*, not a spec field, so rotating it is a rebuild
  of every sandbox rather than a rewrite of every spec.
- each guest's **own host key**, generated inside the guest onto a small
  persistent `identity.img` volume mounted at `/var/lib/sandcastle`. Keeping it
  off `home.img` is what lets a fork copy project state without inheriting the
  parent's guest identity. The CLI pins it in
  `/var/lib/sandcastle/known-hosts/<name>` on first connect and checks it
  strictly afterwards.

`packages.sandbox-example-runner` builds a runner exactly the way `sandcastle
build` does, from the specification in `flake.nix`. It exists for eval and
build coverage without a running host — it carries a throwaway control key, so
it is not meant to be booted. Runtime networking and credential behavior must
be tested through a NixOS host configuration.

## Examples

`examples/flake.nix` contains a minimal downstream host, `sandcastle-host`,
that imports `nixosModules.sandcastleHost` and enables `services.sandcastle`.
Sandboxes are not declared there: they are created at runtime with the CLI.

## Networking Note

The current egress allowlist resolves exact hostnames into nftables IPv4/IPv6
sets and filters by destination IP. It does not enforce wildcard domains, DNS
names, TLS SNI, or HTTP Host headers at packet time. Treat it as a local
hardening prototype until it has been tested on a real KVM host.

## License

Apache-2.0. See `LICENSE`.
