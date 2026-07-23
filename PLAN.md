# agent-sandcastle — High-Level Plan

A self-hosted control plane for spinning up isolated, mobile-controllable Claude Code / Codex sandboxes on a NixOS server. Open source, designed to compose with [microvm.nix](https://github.com/microvm-nix/microvm.nix), [happy.engineering](https://happy.engineering/), and [devenv.sh](https://devenv.sh/).

---

## 1. What it is

A single self-hosted project that gives you:

- A web UI to register a GitLab repo, pick a coding agent (`claude-code`, `codex`, later more), and launch a sandboxed dev VM running that agent against it.
- Each sandbox is a [microvm.nix](https://github.com/microvm-nix/microvm.nix) KVM VM with its own kernel, NIC, and per-VM disk.
- The VM boots with the repo cloned, a [devenv.sh](https://devenv.sh/) shell ready (auto-detected from `devenv.nix` in the repo, or generated from a UI-edited template), and a Happy session already attached to the selected agent.
- Sessions are driven from mobile via a self-hosted [Happy](https://happy.engineering/) relay, with Happy packaged from a pinned upstream revision.
- Sandboxes can be **forked** at any point — the fork inherits repo state, shell history, devenv state. Mechanically: qcow2 backing-file COW, O(1).
- GitLab is connected via OAuth for launcher-side API work. Both **self-hosted GitLab** (Community/Enterprise Edition) and gitlab.com are first-class targets in v1 — the GitLab base URL, OAuth application credentials, SSH host-key pin, and any private CA bundle are NixOS module options on the host. Sandbox VMs receive one project-scoped SSH deploy key each, with Git-only read/write access and no GitLab API token. Branch protection keeps `main` push-protected.

Out of scope for v1: GitHub support, multi-tenant ownership, arbitrary unvetted agent plugins, billing dashboards.

## 2. Goals and non-goals

**Goals**
- Mobile-first agentic coding from anywhere, with end-to-end encryption (Happy).
- Strong isolation between sandboxes and between sandboxes and the host (microvm = independent kernel).
- Cheap forking as a first-class primitive ("try a different approach from this point").
- Reproducible, declarative base image — boring NixOS, no Docker required.
- Reproducible Happy integration: same pinned Happy source builds the VM-side CLI and the host-side relay.
- Agent selection is declarative: the launcher owns an allowlisted registry of supported coding agents and records the resolved command in each sandbox spec.
- v1 is OAuth-only for both supported agents: Claude Code via `claude setup-token` (long-lived `CLAUDE_CODE_OAUTH_TOKEN`) and Codex via `codex login` (per-sandbox `~/.codex/auth.json`). Each sandbox carries its own credential.
- Sandbox VMs see a curated, sandbox-only Nix store. The host's main `/nix/store` is never exposed to a sandbox.
- One-command self-host on any NixOS box.

**Non-goals (v1)**
- Production multi-tenant SaaS. Single-user / single-tenant only.
- Replacing IDEs. The agent UX is Happy on mobile or `ssh`/`mosh` from a terminal.
- Custom container runtime. We use what microvm.nix gives us.
- Anthropic API keys / OpenAI API keys as agent credentials. v1 is OAuth-only for both Claude and Codex; API-key auth modes are deferred until the OAuth lifecycle UX (provisioning, refresh, fork, revocation) is proven.
- Arbitrary user-supplied agent commands. v1 exposes a curated allowlist so the launcher can reason about credentials, expected paths, and restart behavior.

## 3. Architecture

```
                        ┌────────────────────────────────────────┐
   Mobile (Happy app) ──▶ happy.example.com (Caddy → Happy relay)│
                        │                                         │
   Browser ─────────────▶ sandboxes.example.com                   │
                        │   (Caddy → forward_auth Authentik)      │
                        │   (→ agent-sandcastle launcher)         │
                        │                                         │
                        │   ┌──────────────────────────────────┐  │
                        │   │ launcher (unprivileged Phoenix) │  │
                        │   │  - web/API + SQLite             │  │
                        │   │  - Authentik authorization      │  │
                        │   │  - opaque credential UUIDs      │  │
                        │   │  - path-free sandbox specs      │  │
                        │   └──────────────┬───────────────────┘  │
                        │        root:agent-sandcastle 0660       │
                        │          systemd-owned Unix socket      │
                        │   ┌──────────────▼───────────────────┐  │
                        │   │ lifecycle broker (root, Go)      │  │
                        │   │  - one process per connection    │  │
                        │   │  - credential UUID resolution    │  │
                        │   │  - VM definitions/qcow2/systemd  │  │
                        │   │  - Codex auth persistence        │  │
                        │   └──────────────┬───────────────────┘  │
                        │   ┌──────────────▼───────────────────┐  │
                        │   │ microvm.nix VMs (one per sandbox)│  │
                        │   │  - sandbox-only /nix/store        │  │
                        │   │    (virtiofs RO, curated, never  │  │
                        │   │     the host's main store)        │  │
                        │   │  - tmpfs overlay for writes       │  │
                        │   │  - per-VM qcow2 for /home/dev    │  │
                        │   │  - base image: claude/codex/...  │  │
                        │   │  - Happy session: chosen agent    │  │
                        │   │    → relay (outbound only)        │  │
                        │   └──────────────────────────────────┘  │
                        └────────────────────────────────────────┘
```

Four components, two repos:

| Repo | Contains |
|---|---|
| `agent-sandcastle` (this project) | NixOS modules for the base image, sandbox VM template, launcher service; launcher source code |
| Downstream consumer (e.g. someone's NixOS host config) | `inputs.agent-sandcastle.url = "github:…"` and a few lines wiring it up |

The Happy relay is its own NixOS module shipped alongside, since it's tightly
co-deployed. The launcher and broker are deliberately separate security
principals: Phoenix never receives host credential paths, `/dev/kvm`, sudo,
systemd control, or write access to the microVM state tree.

### Initial deployment topology and future split

The first deployment co-locates the launcher, broker, microVM worker, Foundry
VTT, Authentik, PostgreSQL, and observability on the existing Foundry host. This
is an intentional single-user prototype topology, not a claim that arbitrary
multi-tenant compute belongs beside the rest of the services forever.

The host has enough capacity for the control plane and a small number of
sandboxes. Start with at most two active sandboxes, all owned by explicitly
trusted `sandbox-admins`, and only trusted/private repositories. Put the whole
Sandcastle workload in a dedicated systemd slice with aggregate CPU, memory,
process, file-descriptor, and I/O controls so agent builds cannot starve the
game server, identity provider, database, backups, or monitoring.

Keep the complete Sandcastle plane relocatable as one unit:

- launcher
- lifecycle broker and its Unix socket
- credential staging root
- microVM definitions, disks, and curated store
- sandbox bridge and firewall

Move that unit to a dedicated KVM host when access expands beyond the small
trusted group, sandboxes execute untrusted external pull requests, more than two
or three VMs need to run concurrently, Foundry latency becomes visible, or the
stored code/credentials become materially valuable. Do not split it into a
distributed system before those triggers occur. If trusted Authentik headers
ever cross a host boundary, protect the proxy channel with a private,
authenticated transport or replace header trust with direct token validation.

Relevant primary documentation behind this decision:

- [Coder external provisioners](https://coder.com/docs/admin/provisioners):
  built-in provisioners are the default, while external provisioners isolate
  build execution, APIs, secrets, and load when the deployment grows.
- [Coder Agents architecture](https://coder.com/docs/ai-coder/agents/architecture):
  separates control-plane orchestration from workspace execution, uses
  outbound workspace connections, and keeps provider credentials out of
  workspaces where its execution model permits.
- [GitHub ephemeral self-hosted runners](https://docs.github.com/en/actions/reference/runners/self-hosted-runners)
  and [GitLab runner security](https://docs.gitlab.com/runner/security/):
  recommend disposable, isolated execution and network segmentation for
  user-controlled jobs.
- [microvm.nix compartmentalization](https://microvm-nix.github.io/microvm.nix/)
  and [Firecracker production host guidance](https://github.com/firecracker-microvm/firecracker/blob/main/docs/prod-host-setup.md):
  support VM boundaries, minimal guest stores, host-side resource controls, and
  explicit egress filtering. Firecracker is an analogous production reference;
  the current Sandcastle hypervisor is QEMU.
- [systemd socket activation](https://www.freedesktop.org/software/systemd/man/252/systemd-socket-activate.html):
  supports launching one helper instance per accepted connection, so the narrow
  privileged broker does not need to remain resident.

## 4. Repo layout

```
agent-sandcastle/
├── flake.nix
├── nix/
│   ├── base-image.nix         # read-only NixOS base for sandbox VMs
│   ├── sandbox.nix            # parameterised microvm template
│   ├── sandbox-store.nix      # curated sandbox-only nix store builder
│   ├── launcher-module.nix    # NixOS service for the launcher
│   ├── broker-module.nix      # socket-activated privileged broker service
│   └── happy-relay-module.nix # NixOS service for self-hosted Happy
├── broker/                    # small Go lifecycle/credential broker
├── launcher/                  # Elixir (Phoenix LiveView) — see §5
│   ├── mix.exs
│   ├── lib/
│   ├── priv/
│   ├── assets/
│   └── test/
├── docs/
│   ├── architecture.md
│   ├── self-hosting.md
│   ├── threat-model.md
│   └── operations.md
├── examples/
│   └── flake.nix              # minimal downstream consumer
├── LICENSE                    # Apache 2.0
├── README.md
└── CHANGELOG.md
```

Flake outputs:

- `nixosModules.base` — installs the sandbox base image + microvm.nix runner config on the host
- `nixosModules.launcher` — declares the launcher systemd service, Caddy snippet, sops dependencies
- `nixosModules.broker` — declares the root-owned Unix socket and per-connection broker service
- `nixosModules.happyRelay` — the Happy relay service
- `packages.${system}.launcher` — the launcher binary/release for cachix
- `packages.${system}.broker` — statically linked broker binary
- `packages.${system}.claude-code` — Claude Code imported from `numtide/llm-agents.nix`
- `packages.${system}.codex` — Codex imported from `numtide/llm-agents.nix`
- `packages.${system}.happy-coder` — Happy CLI imported from `numtide/llm-agents.nix`
- `packages.${system}.happy-cli` — compatibility alias for `happy-coder`
- `packages.${system}.happy-server` — Happy relay package, imported from upstream when available or kept as a small local derivation
- `packages.${system}.sandbox-base` — the base image closure
- `packages.${system}.sandbox-store` — the curated, sandbox-only nix store path mounted into every VM

Happy source model:
- Add `numtide/llm-agents.nix` as the default pinned flake input for agent CLI packaging.
- Import Happy, Claude Code, and Codex from that flake so this repo does not duplicate fast-moving package logic.
- For the Happy relay, prefer an upstream/imported output when one exists; otherwise keep a small local derivation pinned to a compatible Happy source revision.
- Expose package override hooks for downstream hosts that want to test a fork without changing this repo's default pin.

## 5. Launcher implementation

**Language: Elixir + Phoenix LiveView.**

Rationale:
- The UX is "live status of N supervised long-running processes" (microvms, log tails, qcow2 sizes, GitLab API operations). LiveView and OTP supervisors map to this exactly.
- A `mix release` is a self-contained tarball, packageable as a NixOS systemd service via `pkgs.beamPackages`.
- Hot reload during dev makes iteration fast.

**Key dependencies**

- Phoenix + LiveView for the UI
- Ecto + SQLite (`ecto_sqlite3`) for state — one file at `/var/lib/agent-sandcastle/state.db`
- Jason for Phoenix/Plug JSON parsing and cookie/session-backed browser flows
- Tesla or Req for the GitLab API client
- A typed Unix-socket client for the root-owned lifecycle broker
- Broker-mediated credential enrollment helpers that run agent login flows in
  isolated temporary homes and return only an opaque credential UUID/status to
  Phoenix
- Development-only browser verification uses Rodney against a headless Chromium from the launcher dev shell.

**State (SQLite)**

```
sandboxes
  id, name, repo_url, gitlab_project_id,
  parent_sandbox_id (NULLable, for forks),
  agent_key, agent_command, agent_auth_mode, happy_session_name,
  qcow2_path, status, created_at, last_active_at
gitlab_oauth_grants
  id, gitlab_user_id, scopes, access_expires_at,
  refresh_token_sops_path, created_at, updated_at
sandbox_deploy_keys
  id, sandbox_id, gitlab_project_id, gitlab_deploy_key_id,
  public_key_fingerprint, private_key_sops_path, can_push,
  expires_at, created_at
agent_credentials
  id, sandbox_id, agent_key, auth_mode,
  credential_id, writable, last_persisted_at,
  expires_at, created_at, revoked_at
happy_sessions
  id, sandbox_id, relay_url, session_name,
  state_reset_at, last_seen_at, status
audit_log
  id, sandbox_id, action, actor, ts, payload_json
```

**Privileged lifecycle broker**

Use a small Go program for the host privilege boundary. Go gives this
I/O-heavy, protocol-oriented component a compact static binary, straightforward
Unix-socket and peer-credential support, memory safety, fast builds, and a
smaller operational surface than adding another VM-management framework.
Rust would also be a strong choice but adds implementation complexity that is
not justified by this narrow protocol. Elixir would unnecessarily place BEAM
and launcher dependencies inside the root boundary; Python, shell, and C make
input validation or memory safety harder to defend.

The broker is not an always-running coordinator. systemd owns an
`AF_UNIX` stream socket with owner `root`, group `agent-sandcastle`, and mode
`0660`, then starts one hardened broker instance per accepted connection
(`Accept=yes`). The connection is mapped to standard input/output or passed as a
single socket descriptor. The process handles one bounded request, returns one
bounded response, and exits.

Protocol and service requirements:

- Versioned, typed JSON request/response envelopes with strict decoding,
  unknown-field rejection, maximum message size, deadlines, and bounded output.
- Bound accepted-connection concurrency and systemd activation rate so a buggy
  or compromised launcher cannot fan out an unbounded number of root processes.
- A small allowlist of idempotent operations: initially `ping`, `status`, and
  render validation; later fixed `create`, `start`, `stop`,
  `persist-codex-auth`, `delete`, and fork/flatten operations.
- No arbitrary command, unit name, filesystem path, Nix expression, environment
  variable, or systemd property supplied by the caller.
- Resolve server-generated credential UUIDs only beneath one fixed,
  root-owned staging root. Reject symlinks, traversal, unexpected ownership,
  mode, type, and credential shape.
- Authenticate the local caller with the Unix peer credentials in addition to
  socket permissions. Journal the operation, sandbox ID, authenticated web
  actor forwarded by the launcher, result, and correlation ID without logging
  credential contents or resolved secret paths.
- Root-owned per-sandbox locks and idempotency keys prevent concurrent,
  duplicated, or reordered lifecycle transitions.
- Return batched status data so the dashboard does not create one root process
  per row on every LiveView refresh.
- The broker generates and validates all filesystem and systemd identifiers
  from canonical sandbox UUIDs. It invokes fixed absolute executables with
  fixed argument shapes and a minimal environment.
- Apply strong systemd confinement while retaining only the exact filesystem,
  KVM/TAP, and service-manager access required by the implemented operation.

Start with `ping` plus UUID resolution tests before enabling lifecycle
mutations. Real lifecycle activation remains blocked until Claude and Codex
credential behavior is runtime-validated on Foundry and Codex refresh
persistence/failure ordering is proven.

**Agent registry**

The launcher ships a small allowlisted agent registry, declared in the NixOS module and exposed read-only at `/admin/agents`. The registry is **not** mutable through the web UI: changes require editing the host config and reloading. This keeps the admin route from being a remote-execution vector if Authentik is ever misconfigured.

| Key | Display | VM command |
|---|---|---|
| `claude-code` | Claude Code | `claude` or the packaged Claude Code command |
| `codex` | Codex | `codex` |

Each registry entry declares:
- Command and arguments to run inside the repo directory.
- Auth mode and required credential surface (e.g. `CLAUDE_CODE_OAUTH_TOKEN` env var, writable `~/.codex/auth.json`).
- Whether the agent supports non-interactive bootstrap flags, resume flags, or project-local config.
- Health-check hints used by the launcher UI.

When a sandbox is created, the launcher stores the selected `agent_key`, the resolved command, and the auth mode in the sandbox record and generated microvm definition. This keeps historical sandboxes reproducible even if the default registry changes later.

**v1 auth modes**

v1 is OAuth-only for both supported agents. API-key fallbacks are deferred so the launcher only has to reason about one credential lifecycle per agent.

- `claude-code` → `claude-oauth-token` (only mode).
  - A broker-mediated helper runs the launcher-guided `claude setup-token`
    flow in an isolated temporary home, persists the token, and returns only
    status plus an opaque UUID. The staged credential is mounted read-only into
    the sandbox as `CLAUDE_CODE_OAUTH_TOKEN`. It is treated as a high-value
    account credential revocable from Claude.ai.
  - The wrapper never passes `claude --bare` (which ignores `CLAUDE_CODE_OAUTH_TOKEN`).
- `codex` → `codex-chatgpt-oauth` (only mode).
  - A broker-mediated helper runs the launcher-guided `codex login` flow in an
    isolated `CODEX_HOME`, persists the resulting `auth.json`, and returns only
    status plus an opaque UUID. It is mounted into the sandbox as a
    **writable** per-VM file at `/home/dev/.codex/auth.json`. Codex refreshes
    the session token in place; the broker validates and persists it after the
    VM has stopped.
  - One `auth.json` per sandbox. Forks always trigger a fresh `codex login` so each sandbox has an independent, individually revocable session — mirroring the Claude OAuth fork policy.

**HTTP/UI surface**

- `/` — dashboard: list sandboxes with live status (LiveView)
- `/sandboxes/new` — register repo + branch + coding agent + agent auth mode + devenv template form
- `/sandboxes/:id` — detail: status, Happy session status, selected agent, log tail, restart session, fork button, stop/delete
- `/repos` — list registered repos, default-branch protection state, "Apply protection" button
- `/admin/agents` — read-only view of the configured agent registry: enabled agents, resolved commands, allowed auth modes. Mutations require editing the NixOS module and reloading the launcher; the route never writes to disk.
- `/admin/health` — relay status, microvm host status, base image version, sandbox-store generation
- `/api/...` — JSON for scripted use (mirrors the LiveView actions)

Auth: every route behind Caddy `forward_auth` to Authentik. Launcher reads `X-Authentik-Username` and `X-Authentik-Groups`; gates admin actions on `sandbox-admins` group membership.

**Development verification**

Launcher UI changes should run:
- `mix format --check-formatted`
- `mix test`
- `nix flake check --no-build`
- A Rodney browser smoke test against the running Phoenix dev server.

The Rodney smoke path covers the dashboard, `/sandboxes/new`, LiveView client connection, sequential form entry, sandbox creation, the detail page's rendered `mkSandbox` spec, desktop/mobile no-horizontal-overflow assertions, and at least one accessibility-tree lookup for a key heading. Use `rodney start --local` from the repository root so browser state stays in ignored `.rodney/`; if Rodney cannot launch a browser, start the Nix-provided `chromium` with a remote-debugging port and `rodney connect` to it.

Current frontend lessons:
- Phoenix browser sessions require a `secret_key_base` of at least 64 bytes in dev/test too.
- `Plug.Parsers` with `Phoenix.json_library()` needs `Jason` in dependencies.
- LiveView forms need the Phoenix and Phoenix LiveView JavaScript loaded; server-rendered HTML alone is not enough for `phx-submit`.
- The launcher dev shell should include `inotify-tools`, or LiveReload logs warnings and does not watch files.
- Rodney field entry should be sequential for LiveView forms because validation patches can overwrite simultaneous typed values.

## 6. Sandbox lifecycle

### GitLab instance configuration (one-time, at host config time)

The launcher targets exactly one GitLab instance per deployment, configured via the NixOS module:

```nix
services.agent-sandcastle.gitlab = {
  baseUrl = "https://gitlab.example.com";   # or "https://gitlab.com"
  oauthApplicationId = "...";                # from GitLab Admin → Applications
  oauthClientSecretSopsPath = "gitlab-oauth-client-secret";
  sshHost = "gitlab.example.com";            # SSH endpoint (often == baseUrl host)
  sshPort = 22;                              # or 2022 etc. for non-standard installs
  sshHostKeysSopsPath = "gitlab-ssh-host-keys"; # pinned known_hosts entries
  caCertSopsPath = null;                     # set to a sops path for private-CA installs
};
```

This drives:

- The OAuth redirect URI registered on the GitLab side (`https://sandboxes.example.com/auth/gitlab/callback`).
- The egress allowlist entry in §9 (the configured GitLab `sshHost` and `baseUrl` host are both whitelisted; nothing else GitLab-shaped is).
- The SSH config rendered into every sandbox at first boot — `Host gitlab` block with `HostName`, `Port`, `IdentityFile`, `IdentitiesOnly yes`, and `UserKnownHostsFile` pointing at the pinned host-key file. Host keys are fetched once at host config time (`ssh-keyscan`) and stored in sops; the launcher refuses to clone if the live key doesn't match the pinned one.
- The CA bundle staged into the sandbox base image. For self-hosted GitLab fronted by a private CA, the configured `caCertSopsPath` is decrypted on the host, baked into `/etc/ssl/certs/ca-bundle.crt` for the sandbox closure (via `security.pki.certificateFiles`), and any host-side `glab` calls in the launcher pick it up too. Public-CA instances (gitlab.com, Let's Encrypt) leave this `null`.
- The `glab` / Tesla client base URL inside the launcher.

Self-hosted-only quirks worth surfacing:
- Some self-hosted instances put the SSH endpoint on a different hostname or non-22 port; the launcher's clone URL builder uses the configured `sshHost` + `sshPort`, not the `baseUrl` host.
- Air-gapped instances often issue tokens against a private CA; the staged CA bundle is what makes `git clone`, `glab`, and the OAuth redirect dance work without `GIT_SSL_NO_VERIFY` hacks.
- Self-managed instances may have stricter rate limits or different scopes available; the launcher pre-flights `GET /api/v4/version` to surface "this instance is too old / scopes mismatch" before the user gets midway through a flow.

### Create
1. User submits: GitLab repo URL, branch (default: repo default), coding agent choice, devenv template choice. (Auth mode is implicit in v1: `claude-oauth-token` for `claude-code`, `codex-chatgpt-oauth` for `codex`.)
2. If no GitLab OAuth grant exists, launcher redirects through GitLab authorization-code OAuth with scope `api`. **A dedicated GitLab service account with Maintainer access on each managed project is required in v1**, not "preferred": deploy keys persistently inherit their creator's identity, and tying that to a human account means the deploy-key fleet silently destabilises the day that human leaves the org. The refresh token is sops-managed on the host and never mounted into a VM.
3. Launcher uses the current OAuth access token to:
   - Resolve project id via `GET /projects?search=...`.
   - Verify the authenticated GitLab user can manage deploy keys for the selected project (Maintainer or Owner) and that the connected user is the configured service account.
   - Check default branch protection state.
4. Launcher asks the broker to generate a fresh per-sandbox `ed25519` SSH
   keypair. The broker persists the private key and returns the public key,
   fingerprint, and an opaque credential UUID—never a private-key path.
5. Launcher creates a project deploy key via
   `POST /projects/:id/deploy_keys` with the returned public key,
   `can_push=true`, a descriptive title, and an expiry. The deploy key is
   **not** added to any protected-branch `allowed_to_push` rule—doing so would
   grant the service account direct push to protected branches.
6. Launcher resolves the selected agent registry entry and requests a guided
   credential-enrollment operation. A root-owned helper runs the login in an
   isolated temporary home, persists the material, and returns only an opaque
   credential UUID/status to Phoenix:
   - For `claude-code`, run `claude setup-token`, surface only the login
     URL/code through the UI, and persist the captured token as the read-only
     Claude credential.
   - For `codex`, run `codex login` with an isolated `CODEX_HOME` and persist
     the resulting `auth.json`. The broker stages it into a per-VM **writable**
     directory before boot so Codex can refresh tokens in place; on VM stop,
     the broker validates and persists the refreshed file.
7. Launcher generates a unique Happy session name (for example `<sandbox-name>-<short-id>`).
8. Launcher renders and stores a path-free Nix function whose
   `credentialSource` argument is unresolved for preview and audit. It sends
   the broker only typed create fields: canonical sandbox UUID, opaque
   credential UUID, allowlisted agent key, repo metadata, and attribution. The
   preview Nix text is not a broker protocol input, and Phoenix never sends or
   receives a host credential path.
9. Broker validates the request and resolves the credential UUID beneath its
   fixed root-owned staging root. It independently materializes the final
   definition from a broker-owned template and the typed fields, supplies the
   resolved `credentialSource`, validates the result, and writes VM state
   beneath the broker-owned Sandcastle tree. A compromised launcher cannot ask
   the broker to evaluate arbitrary Nix text.
10. Broker creates the per-sandbox qcow2 with an explicit backing format:
    `qemu-img create -f qcow2 -F qcow2 -b base.qcow2 <name>.qcow2`. It then
    starts the allowlisted `microvm@<derived-name>` unit. No request may supply
    an arbitrary path or systemd unit name, and no per-sandbox
    `nixos-rebuild switch` is performed.
11. VM boots. First-boot service inside VM:
   - Reads the sandbox deploy-key private key from the per-VM secrets dir (virtiofs-mounted from a host-side staged dir, **not** from `/run/secrets` directly — see §11).
   - Reads only the selected agent credential from the same per-VM secrets dir. For Codex, the mount is writable.
   - Installs an SSH config entry derived from the configured GitLab instance (`HostName`, `Port`, `IdentityFile`, `IdentitiesOnly yes`, `UserKnownHostsFile` pointing at the staged pinned host-key file). Refuses to proceed if the live host key doesn't match the pin.
   - `git clone git@<configured-gitlab-ssh-host>:group/repo.git /home/dev/<repo>` (the launcher renders the actual clone URL into the staged sandbox-init unit; the example uses the configured `sshHost` from the GitLab module).
   - Detects `devenv.nix`. If absent, writes the user-supplied template to `/home/dev/<repo>/devenv.nix` (uncommitted).
   - Writes `/home/dev/.agent-sandcastle/current-sandbox-id`. If this marker does not match the generated VM identity (common after a fork), reset inherited Happy and agent runtime state (including any inherited `~/.codex/auth.json`) before starting the new session.
   - Starts `happy-session.service`, configured with `HAPPY_SERVER_URL=https://happy.example.com`, `HAPPY_SESSION_NAME`, repo working directory, the resolved agent command, and the selected OAuth credential surface.
12. `happy-session.service` runs as `dev`, after `sandbox-init.service`, in the repo directory. It uses a tiny `sandbox-happy-session` wrapper so Happy CLI syntax changes are isolated to one script; conceptually it connects outbound to the relay and launches the selected coding agent.
13. Mobile app shows the new session already running the chosen agent.

Deploy keys are the narrow v1 Git credential: Git over SSH only, scoped to one project, no GitLab public API access, and revocable by deleting the deploy key. Service-account-owned deploy keys avoid the "deploy key keeps working after human leaves" trap documented in [GitLab's deploy keys docs](https://docs.gitlab.com/user/project/deploy_keys/). GitLab [deploy tokens](https://docs.gitlab.com/user/project/deploy_tokens/) are useful for clone-only sandboxes, but their repository scope is read-only. GitLab's [Project Access Tokens API](https://docs.gitlab.com/api/project_access_tokens/) can create project-scoped HTTPS/API tokens with bot users; we keep that as an optional mode for v2, not the v1 default.

### Fork
1. User clicks "Fork" on an existing sandbox. The fork dialog defaults to the parent's coding agent but may choose another enabled agent (auth mode is fixed by agent in v1).
2. Launcher pauses the parent VM (or takes a live snapshot — start with pause, simpler).
3. `qemu-img create -f qcow2 -F qcow2 -b parent.qcow2 child.qcow2`. The `-F qcow2` is mandatory.
4. Generates a fresh deploy key for the child sandbox. Forks never share Git credentials.
5. Always runs a fresh OAuth login for the child (`claude setup-token` for Claude, `codex login` for Codex) and materializes a new per-child credential. Forks never share agent OAuth credentials with the parent — this gives each sandbox its own revocation surface, matters more for Codex where the same `auth.json` would otherwise be refreshed by two VMs concurrently and last-writer-wins.
6. Generates a fresh Happy session name and new microvm definition referring to the child qcow2.
7. Boots the child VM.
8. Child inherits: repo state, shell history, devenv state, in-progress edits. It does **not** share Git credentials, agent OAuth credentials, Happy runtime identity, or local agent auth caches with the parent.
9. On first boot, the child sees the sandbox-id marker mismatch, clears inherited Happy/Claude/Codex runtime state (including `~/.codex/auth.json` from the parent's qcow2 — replaced by the child's freshly mounted file), and starts a new Happy session with the selected agent.

**Backing-chain depth.** Fork is O(1) at creation, but read I/O cost grows with chain depth because every read may walk every parent. The launcher tracks chain depth in SQLite and runs an offline `qemu-img rebase` / `commit` flatten when depth exceeds 4 (configurable). Flattening requires the descendant to be stopped. The UI shows current chain depth on the sandbox detail page.

### Stop / Delete
- **Stop**: broker requests a graceful VM stop, waits for a proven stopped
  state, validates and persists any writable agent credential (notably refreshed
  Codex `auth.json`) back to its durable credential record, then reports stop
  success. If persistence fails, report a failed/quarantined transition rather
  than claiming success or restarting from stale auth. Keep qcow2 + deploy key.
- **Delete**: after the broker proves the VM stopped, the launcher deletes the
  GitLab deploy key and the broker removes the corresponding private key,
  per-sandbox agent credential, Happy runtime state, VM definition, and qcow2.
  Document the provider-side revocation step because deleting local state does
  not invalidate an already-issued OAuth token.
- **Hard-block delete on a parent that has live (non-deleted) children.** Deleting a parent silently breaks the children's backing chain. The launcher refuses the operation and surfaces a "flatten children first" action.

### Deploy key rotation
- Deploy keys can expire. A daily systemd timer identifies keys approaching
  expiry. The broker generates and stages replacement private keys, while the
  launcher registers/revokes the corresponding GitLab public deploy keys.
- Because secrets are virtiofs-mounted, a rotation requires a sandbox VM **restart** to take effect — virtiofs does not propagate sops remounts to the guest (see §11). The rotation timer schedules a restart of each affected VM after key rollover.
- To invalidate a deleted or suspected-leaked sandbox credential immediately,
  the launcher deletes the GitLab deploy key and asks the broker to kill the
  VM and remove the private credential. Killing precedes local removal so an
  in-flight `git push` cannot race the revocation.

## 7. Base image (`nix/base-image.nix`)

A NixOS module producing a microvm.nix-compatible read-only root.

**Installed:**
- `glab`, `gh` (for completeness), `git`, `git-lfs`
- `claude-code`, `codex`, `happy` (imported from `numtide/llm-agents.nix`; `happy-cli` is the local alias for `happy-coder`)
- `sandbox-happy-session` wrapper script used by systemd to launch Happy with the selected agent
- `devenv`, `direnv`, `nix-direnv` (with direnv `flakes = true`)
- `python3`, `nodejs`, `go`, `cargo`/`rustc` (from nixpkgs — no `rustup`, since rustup-managed toolchains write into qcow2 per VM and bypass the curated sandbox store), `uv`, `pnpm`, `bun`
- `ripgrep`, `fzf`, `jq`, `yq`, `htop`, `less`, `vim`, `helix`, `tmux`, `mosh`
- `openssh`, `ca-certificates`, `mtr`, `dig`

**System config:**
- One unprivileged user `dev` with sudo to nothing
- `services.openssh.enable` (key only, for emergency direct access)
- systemd unit `sandbox-init.service` runs the first-boot clone + devenv setup
- systemd unit `happy-session.service` runs the Happy CLI in connect-out mode and launches the selected agent
- `happy-session.service` uses `Restart=on-failure`, depends on `network-online.target` and `sandbox-init.service`, and writes logs to journald for the launcher to tail
- Networking: DHCP on the VM's NIC; egress NATed by host (and allowlisted — see §9)
- `/nix/store` provided by the **curated sandbox store** via virtiofs, read-only — never the host's main `/nix/store` (see §8)
- CA trust: when `services.agent-sandcastle.gitlab.caCertSopsPath` is set, the decrypted bundle is added to the sandbox closure via `security.pki.certificateFiles` so `git`, `glab`, `curl`, Node-based tooling, and the OAuth dance trust the self-hosted GitLab instance without per-tool overrides
- tmpfs overlays on `/tmp`, `/var/tmp`, and `/home/dev/.cache` to work around virtiofs lacking `O_TMPFILE` support, which Node-based tooling (Claude Code, Happy CLI) and many build tools rely on

**Closure size target:** ~3 GB. Shared across all sandboxes via the curated sandbox store on the host (see §8).

## 8. Sandbox VM template (`nix/sandbox.nix`)

Exposes a `mkSandbox { name, repoUrl, branch, agentKey, agentCommand, agentAuthMode, agentCredentialSecret, agentCredentialWritable, happySessionName, parentDisk ? null, ... }` function returning a microvm.nix module fragment:

- Hostname = `sandbox-${name}`
- 2 vCPU, 2 GB RAM (configurable)
- One virtio-blk disk = the per-sandbox qcow2 (mounted as `/home/dev`)
- Virtiofs RO share: a tagged `source = "/nix/store"` share, mounted as `/nix/.ro-store` in the guest. The host rewrites what `virtiofsd` serves so the guest receives the **curated sandbox nix store** at `/var/lib/agent-sandcastle/store/nix/store`, not the host's main store. microvm.nix then bind-mounts or overlays that read-only lower store into the guest's final `/nix/store`. This is a single sandbox-wide path,[^runner-closure] populated by `agent-sandcastle-sandbox-store.service` (see below).
- A small writable store overlay (tmpfs upper layer on a per-VM block device) so guest-local `nix build` and `devenv` invocations can extend the curated store without polluting the host. Per microvm.nix docs the overlay must sit on a block device, not on the virtiofs share.
- Virtiofs RO share: per-VM secrets dir for the deploy-key private key and the read-only Claude OAuth token (when applicable). Source path is a per-VM staged dir on the host (see §11), **not** `/run/secrets`; the guest mounts it under `/run/agent-sandcastle/secrets` and units bind/symlink individual files to their final paths.
- Virtiofs RW share: per-VM Codex auth staging dir when `agentKey == "codex"` and `agentCredentialWritable == true`, so Codex can refresh the token in place. The guest mounts it under `/run/agent-sandcastle/codex-auth`, exposes `/home/dev/.codex/auth.json` as a bind/symlink to that staged file, and the host persists `/var/lib/agent-sandcastle/codex-auth/<sandbox>/auth.json` back into sops on stop.
- Generated `/etc/agent-sandcastle/session.env` with repo path, selected agent, agent auth mode, Happy relay URL, and Happy session name.
- Tap device `tap-${name}` bridged to a sandboxes-only bridge with NAT.
- Egress firewall: see §9 — default-on allowlist with provider endpoints for the selected agent, GitLab, Happy relay, and language registries.
- Includes the base-image module from §7.

**Curated sandbox store and mount constraints** (`nix/sandbox-store.nix`)

`microvm.nix` treats a host-provided store specially only when a share's `source` is literally `"/nix/store"`. Its guest mount logic finds `hostStore` by filtering `microvm.shares` on `source == "/nix/store"`, and `microvm.storeOnDisk` uses the same test to skip building a per-VM store disk. Upstream docs and public Nix examples follow that convention, often mounting the share at `/nix/.ro-store` and then binding or overlaying it into `/nix/store`. A share such as `source = "/var/lib/agent-sandcastle/store/nix/store"; mountPoint = "/nix/store";` would not satisfy that machinery.

Agent Sandcastle therefore declares the store share as:

```nix
microvm.shares = [{
  source = "/nix/store";
  mountPoint = "/nix/.ro-store";
  tag = "agent-sandcastle-curated-store";
  proto = "virtiofs";
  readOnly = true;
}];
```

The host module then scans VM definitions for that tag and installs a drop-in on `microvm-virtiofsd@<name>.service`:

```nix
serviceConfig = {
  PrivateMounts = true;
  BindReadOnlyPaths = [
    "${config.services.agent-sandcastle.sandboxStore.path}/nix/store:/nix/store"
  ];
};
```

Inside `virtiofsd`'s private mount namespace, `/nix/store` is the curated chroot store. The runner still passes `--shared-dir=/nix/store`, satisfying `microvm.nix` while keeping the host's real `/nix/store` invisible to the guest. The guest mount point stays `/nix/.ro-store` so writable-store overlay mode has a stable lowerdir and non-overlay mode can let microvm.nix bind it into `/nix/store`.

A host-side NixOS service `agent-sandcastle-sandbox-store.service` realises the declared closure roots into `/var/lib/agent-sandcastle/store` using `nix copy --to "local?root=/var/lib/agent-sandcastle/store"`. The API is explicit:

```nix
services.agent-sandcastle.sandboxStore.closureRoots = [
  config.microvm.vms.smoke.config.config.system.build.toplevel
  config.microvm.vms.smoke.config.config.microvm.declaredRunner
];
```

For each curated-store VM, the host config supplies the VM toplevel plus `microvm.declaredRunner`; the VM toplevel brings in the base image, enabled agent profiles, and Happy CLI. The launcher and host module should extend this option rather than inventing a second closure-root interface. The service runs on host config changes and agent-registry edits; it never copies anything that is not part of the declared sandbox runtime. Net effect: sandboxes share one curated store (no per-VM closure duplication) without ever seeing the host's main store, the launcher's closure, or the relay's closure.

[^runner-closure]: The curated store must also contain each VM's microvm runner closure, including helper scripts, `virtiofsd`, `supervisord`, and the shell used by `virtiofsd-run`. Those paths may be readable inside the guest, but they are inert there and do not change the §13 threat model.

**Host-side reconciliation by share tag**

Guest modules declare host-side work by attaching stable tags to `microvm.shares` entries. The host module inspects evaluated `config.microvm.vms.<name>.config.config.microvm.shares`; the tag is the marker, so there is no separate per-VM "curated store enabled" option to keep in sync. Current use: `agent-sandcastle-curated-store` triggers the virtiofsd namespace drop-in above. The same pattern should be used for per-VM secret-staging dirs (§11), egress allowlist extensions (§9), and SSH host-key staging (§6): the guest-facing share declares intent, and the host reconciles the matching service, files, or firewall state.

## 9. Networking and isolation

- Each sandbox gets its own tap interface and IP on a private bridge (`br-sandboxes`).
- Host runs nftables NAT for egress. Before lifecycle activation, add an
  unconditional drop for traffic destined for the host, loopback, LAN/private
  and link-local ranges, management services, and other sandbox interfaces.
- Required end state: no sandbox can reach Authentik, PostgreSQL, the launcher,
  the curated-store builder, host management services, or another sandbox.
- **Egress allowlist is on by default in v1.** Default allowed: provider endpoints for the selected agent (`*.anthropic.com` for Claude, `*.openai.com` / `chatgpt.com` for Codex), the configured GitLab instance (both `services.agent-sandcastle.gitlab.baseUrl` and `sshHost`, which may differ for self-hosted installs), the Happy relay (`happy.example.com`), and a small set of language registries (`registry.npmjs.org`, `pypi.org`, `crates.io`, `proxy.golang.org`). Anything else is dropped. Self-hosted GitLab installs that mirror packages on internal hostnames (`packages.gitlab.example.com`, container registries, etc.) declare those alongside the base URL in the module options.
- **Enforcement is host-side, not in-VM.** The current allowlist is implemented
  in nftables on the host, matching sandbox interfaces and destination IPs, so
  a compromised guest cannot rewrite its own firewall. It resolves exact
  configured hostnames to IPv4/IPv6 sets during allowlist refresh; it does not
  enforce DNS names, wildcard domains, TLS SNI, or HTTP Host at packet time. An
  optional forward proxy may later add name-aware policy and request logging.
- Per-sandbox extensions to the allowlist are declared in the microvm definition and reconciled into nftables; ad-hoc runtime mutations are not supported.
- The bridge, DHCP/DNS, NAT, TAP attachment, curated-store boot, allowed OpenAI
  destination, and blocked unlisted destination have been runtime-validated on
  Foundry. Before lifecycle activation, add explicit rules that block guest
  access to the host, loopback, other sandboxes, LAN/private ranges, link-local
  addresses, and management services regardless of resolved allowlist entries.
- Place all VMs in a dedicated systemd slice and apply aggregate concurrency,
  CPU, memory, process, file-descriptor, log, disk-growth, and I/O limits.
- Limitation: a domain-allowlist firewall does not prevent exfiltration *through* an allowed domain (e.g. pushing to a GitLab branch). That risk is mitigated by branch protection (§12) and per-sandbox deploy keys, not by the firewall.

## 10. Happy integration and relay

Happy is first-class infrastructure for this project, but not vendored by default.

**Source/package integration**

- `flake.lock` pins `numtide/llm-agents.nix`, which in turn pins upstream Happy and related agent tool sources.
- The VM-side Happy CLI comes from `packages.${system}.happy-coder`, exposed locally as both `happy-coder` and `happy-cli`.
- Claude Code and Codex come from the same imported package set, keeping agent packaging updates centralized.
- The host-side relay should use an imported Happy relay output when available; otherwise it gets a narrow local derivation pinned to a compatible Happy source revision.
- Default integration is a pinned Nix input, not a git submodule.
- A fixed submodule under `vendor/happy` is a later escape hatch for local patches, source-vendoring audits, or temporary relay packaging gaps. If added, it should still feed the same local package names so the rest of the system does not care where the source came from.
- Downstream hosts may override the imported packages through NixOS module options when testing forks or newer pins.

**Relay module**

Modeled on existing native services:
- Single Node systemd unit, port 3005 on 127.0.0.1
- Postgres tenant + Redis instance + filesystem storage at `/var/lib/happy`
- Required environment: `DATABASE_URL`, `REDIS_URL`, `PORT`, `NODE_ENV=production`, and `SEED` (the upstream env var for token generation; replaces what an earlier draft of this plan called `HANDY_MASTER_SECRET`, which is not an upstream variable).
- One sops secret: `happy-seed`, exposed as `SEED` to the relay unit only.
- Caddy vhost `happy.example.com` with websocket support
- Restic includes `/var/lib/happy`
- No Authentik in front — the protocol is its own E2E-encrypted thing. The relay only sees encrypted blobs; the master secret used for client-side encryption never leaves the user's mobile device.

The relay is **not** the agent. It forwards encrypted blobs. The VM-side Happy session launches the selected agent, and the sandbox only receives the OAuth credential required for that agent.

**Sandbox session autostart**

- The launcher renders `happy-session.service` into every sandbox VM from the selected agent profile.
- The service runs as user `dev`, starts only after repo clone/devenv setup, and uses the repo root as `WorkingDirectory`.
- The service runs `sandbox-happy-session`, which wraps the Happy CLI and launches the selected command (`claude`, `codex`) inside the Happy session.
- For `claude-oauth-token`, the wrapper exports `CLAUDE_CODE_OAUTH_TOKEN` from the read-only mounted secret and clears any inherited `~/.claude/.credentials.json` before startup. The wrapper never passes `claude --bare` (which ignores `CLAUDE_CODE_OAUTH_TOKEN`).
- For `codex-chatgpt-oauth`, the wrapper sets `CODEX_HOME=/home/dev/.codex` and ensures `/home/dev/.codex/auth.json` is the writable virtiofs-mounted file from the host. Codex refreshes the session token in place during normal use.
- The Happy session name is generated by the launcher and stored in SQLite so the dashboard can display the exact mobile session to open.
- Restarting the Happy session is a launcher action implemented by a fixed
  broker operation that restarts only the derived `happy-session.service`, not
  the whole VM.
- On VM stop, the broker coordinates a root-owned persist helper that validates
  and writes the latest `auth.json` for that sandbox back to durable encrypted
  storage, so the next boot receives the refreshed tokens.
- Forks always receive a new Happy session name and reset inherited Happy and agent runtime state before the child service starts. This keeps mobile sessions, device bindings, OAuth caches, and relay state independent even though the qcow2 disk inherits repo and shell state.

## 11. Secrets management

The unprivileged launcher manages credential metadata and opaque UUIDs. Host
paths, staging, and credential material are owned by the broker and supporting
root-only units. Long-lived encrypted storage uses `sops-nix` on the host:

- `agent-credentials/<name>/claude-code-oauth-token` — per-sandbox Claude Code OAuth token from the launcher-guided `claude setup-token` flow (read-only mount).
- `agent-credentials/<name>/codex-chatgpt-auth-json` — per-sandbox Codex `auth.json` from the launcher-guided `codex login` flow. Staged into a per-VM writable file before boot; persisted back into sops on VM stop.
- `gitlab-oauth-client-secret` — OAuth application secret for the launcher (registered on the configured GitLab instance).
- `gitlab-oauth-refresh-token` — host-only GitLab OAuth refresh token for the connected service account.
- `gitlab-ssh-host-keys` — pinned `known_hosts` entries for the configured GitLab SSH host (`ssh-keyscan`-captured at host config time, staged into every sandbox).
- `gitlab-ca-cert` — optional, only set for self-hosted GitLab fronted by a private CA. Staged into both the launcher and every sandbox so `git`, `glab`, and the OAuth dance trust the instance without `GIT_SSL_NO_VERIFY` hacks.
- `happy-seed` — relay token-generation seed (exported to the relay unit as `SEED`).
- `sandbox-deploy-keys/<name>` — per-sandbox SSH deploy-key private key.

Sandbox VMs do **not** have access to host sops keys. They only see their own
staged secret directory: the per-sandbox deploy key plus exactly one OAuth
credential for the selected agent. Credential staging is excluded from backups,
logs, rendered Nix text, and launcher-visible filesystem paths.

**virtiofs + sops staging.** Mounting `/run/secrets` directly into a guest is unsafe in this stack: every `nixos-rebuild switch` (including auto-updates) remounts `/run/secrets` on the host, which makes the guest mount appear empty until the VM is rebooted ([microvm.nix issue #239](https://github.com/microvm-nix/microvm.nix/issues/239)). v1 mitigates this with two measures:
- Set `sops.keepGenerations = 0` so old generations aren't churned out from under live mounts.
- Stage each VM's secrets into a dedicated per-VM directory beneath one fixed,
  root-owned staging root. Only the broker maps an opaque UUID to that path,
  using beneath/no-symlink semantics and ownership/mode/type validation. A
  oneshot staging unit copies the relevant decrypted sops files with the
  minimum permissions needed by the selected microVM share. The VM definition
  receives the path through its `credentialSource` function argument and never
  embeds a caller-supplied path. It does **not** mount `/run/secrets`.

Trade-off: secret rotation (deploy keys, Claude OAuth tokens) requires re-staging and a sandbox restart; live propagation is not supported. The deploy-key rotation timer in §6 already accounts for this.

Claude and Codex OAuth credentials are treated as high-value account credentials:
- Never bake them into the qcow2 image or shared base image.
- Mount only the credential the sandbox needs (Claude RO, Codex RW) and expose it only to `happy-session.service`.
- Store metadata (creation, last-persisted-at, expiry hint) in SQLite, but store the credential value only in sops.
- On delete, remove the host-side secret and document the provider-side revocation step (Claude.ai → Settings → Devices for Claude; ChatGPT → Settings → Connected apps for Codex), because deleting local state does not invalidate an already-issued OAuth token.

**Storage vs delivery.** Storage is uniform: every secret is a sops-encrypted file on the host, decrypted into the per-VM staged directory at boot. Delivery shape depends on the secret:

- **Env-shaped secrets** (e.g. `CLAUDE_CODE_OAUTH_TOKEN`, future
  `DATABASE_URL`) are loaded into the agent's process tree via systemd's
  `EnvironmentFile=` directive on `happy-session.service`. The root-owned
  staging helper renders one or more `KEY=VAL` files into the staged directory;
  the unit references them by path. Values never appear in launcher-visible
  rendered text, the qcow2 disk, or unit arguments.
- **File-shaped secrets** (e.g. Codex `~/.codex/auth.json`, deploy-key private key, future TLS certs) stay as bind-mounted files. Codex specifically *requires* a writable file because it refreshes the token in place; an env var couldn't carry the rewrite.
- **Interactive shell exposure is opt-in per secret.** By default, `EnvironmentFile=`-loaded secrets are visible only to the agent process tree, not to ad-hoc `bash` or `tmux` shells the user opens via `mosh`/`ssh`. A per-secret "expose to interactive shells too" toggle, when enabled, additionally drops the file into a `direnv`-loaded `.envrc` so it's available in the repo's working shell. Default off because every interactive command (and every tool the agent shells out to) inherits the env, widening the leakage surface.

**Future: user-managed secret bag (post-v1, queued).** A per-sandbox key/value store the user fills in via the launcher UI for things like `DATABASE_URL`, `STRIPE_API_KEY`, etc. Same storage path as agent credentials (sops on host, staged file in per-VM dir, delivered via `EnvironmentFile=`), with these additions:

- A new SQLite table `sandbox_user_secrets (id, sandbox_id, key, sops_path, exposed_to_shells, created_at, updated_at, revoked_at)`.
- UI surface at `/sandboxes/:id/secrets` for create/update/delete, with a clear warning that values are visible to the agent and to anything it spawns.
- The broker's staging helper concatenates per-sandbox user secrets into a
  single `user-secrets.env` file; `happy-session.service` references both
  `agent-credentials.env` and `user-secrets.env` via `EnvironmentFile=`.
- Same rotation model: edit value → re-stage → restart `happy-session.service` (no VM reboot required for env-shaped secrets, since the staging path is per-VM and we only touch the agent unit).
- File-shaped user secrets (e.g. a TLS keypair, a `.pgpass`) get a separate UI affordance with explicit mount path; deferred until env-shaped secrets are in production.

## 12. Branch protection helper

Implements the GitLab [Protected Branches API](https://docs.gitlab.com/api/protected_branches.html):

- `GET /projects/:id/protected_branches` to detect current state
- `POST /projects/:id/protected_branches` with `name=main`, `push_access_level=0`, `merge_access_level=30`, `allow_force_push=false`

UI surface: on the repo registration page and on the per-sandbox page, show current protection state. If `main` permits direct pushes, render an "Apply no-direct-push protection" button. Idempotent.

Document the recipe in `docs/operations.md` so users understand:
- The sandbox deploy key can push feature branches but cannot call the GitLab API.
- `main` must be configured with "Allowed to push and merge: No one" to block direct pushes.
- Do not add sandbox deploy keys to protected-branch `allowed_to_push`; that would intentionally let them push protected branches.
- If the project uses CODEOWNERS, set `code_owner_approval_required=true` on the protected branch so a maintainer can't merge a sandbox-authored MR that bypasses owner review. The launcher exposes a checkbox alongside the "Apply protection" button.

## 13. Threat model (v1)

**In scope**
- Supply-chain code execution from prompts (an LLM `npx`s a malicious package): contained to one VM, can't reach host or other sandboxes; egress allowlist limits exfiltration paths to provider endpoints, GitLab, and the Happy relay.
- Sandbox enumerates host nix store: blocked. Sandboxes mount the curated sandbox store, not the host's `/nix/store`, so the launcher and relay closures (and any host secrets that ended up in derivations) are not visible to any guest. The curated store intentionally includes each VM's microvm runner closure so `virtiofsd-run` works inside its private mount namespace; those binaries are inert inside the guest.
- Stolen mobile device: revoke the Happy device token; sandbox keeps running but no new control.
- Stolen GitLab sandbox deploy key: scoped to one project and Git over SSH only; it cannot call the GitLab API, cannot read other projects, and cannot push to protected `main` when no-direct-push protection is applied.
- Compromised GitLab OAuth grant: limited to the connected service account. v1 mandates a dedicated GitLab service account so a deploy key created by it does not silently outlive a human user's tenure (deploy keys persistently inherit their creator's identity, per GitLab docs).
- Stolen Claude Code sandbox OAuth token: scoped to Claude Code inference but still an account credential. Stored per sandbox via sops, mounted read-only, removed on sandbox delete; revocation requires the user to remove the device from Claude.ai.
- Stolen Codex sandbox OAuth `auth.json`: ChatGPT-account-scoped credential. Mounted writable so Codex can refresh it; on delete the host-side copy and the most recent sops snapshot are removed. Revocation requires the user to remove the connected app in ChatGPT settings.
- Runaway agent loop: provider spend caps and per-account ChatGPT/Anthropic limits cap damage.
- Forked sandbox session confusion: child sandboxes reset inherited Happy and agent runtime state, run a fresh `claude setup-token` / `codex login`, and receive a new Happy session name before autostart.
- Backing-chain corruption: deleting a parent with live children would silently break their disks; the launcher refuses this and surfaces a flatten action.

**Out of scope (acknowledged)**
- Targeted kernel exploit from inside a microvm — possible but exotic; mitigated by keeping the host kernel patched.
- Compromise of the launcher or forged trusted-proxy headers: application-level
  Authentik username plus `sandbox-admins` checks limit normal access, and the
  loopback-only listener prevents external clients from bypassing Caddy.
  Launcher compromise can submit requests as its Unix-socket identity, so the
  broker protocol must remain narrow and independently validate all identifiers
  and transitions; it must not become an arbitrary root command/path oracle.
- Hypervisor or host-kernel escape remains a host compromise. On the initial
  shared Foundry deployment that blast radius includes Foundry VTT, Authentik,
  PostgreSQL, monitoring, and locally available secrets. This is accepted only
  for the trusted, low-concurrency prototype topology described in §3.
- Exfiltration through allowed domains (e.g. pushing data into a public branch on GitLab): not blocked by the egress allowlist. Mitigated by branch protection, CODEOWNERS approval gating, and per-sandbox deploy keys, but a determined prompt-injection attacker can still abuse GitLab's normal write surface.
- Anthropic policy shifts on third-party OAuth: v1 depends on `claude setup-token` and `codex login` continuing to be supported flows. If either is restricted, the launcher would need to fall back to an API-key path (currently a v2 item).

Full doc lives at `docs/threat-model.md`.


## 14. Milestones

**M0 — Foundations (curated-store plumbing + eval/build scaffolding)**
- Repo created, license, README skeleton
- `flake.nix` with nixpkgs + microvm.nix + pinned `numtide/llm-agents.nix` input for Happy/Claude/Codex packaging + (later) relay packaging
- `nix/sandbox-store.nix` and `nix/sandbox.nix` implement the curated-store builder and mount plumbing as one unit: build the curated chroot store, declare the tagged literal `/nix/store` virtiofs source mounted at `/nix/.ro-store`, and install `PrivateMounts` + `BindReadOnlyPaths` drop-ins for selected VMs
- `services.agent-sandcastle.sandboxStore.closureRoots` API documented and wired in the example host from each VM's `system.build.toplevel` and `microvm.declaredRunner`
- `examples/flake.nix` runs `nixos-rebuild build` on a stub host
- No runtime boot guarantee yet; M0 proves the host config evaluates and builds, while M1 proves a guest boots against that store

**M1 — Headless sandbox (no UI yet)**
- `nix/base-image.nix` boots, has all tools, joins a tap bridge
- End-to-end boot confirms the M0 curated-store mount is the only `/nix/store` visible in the guest
- tmpfs overlays in place; Node-based tooling runs without `O_TMPFILE` errors
- Default-on egress allowlist implemented and tested in host nftables
- A hand-written sandbox in `examples/` boots, clones a public repo, starts a Happy session running a default agent, and still allows emergency `ssh`
- A hand-written Claude sandbox can consume a mounted `CLAUDE_CODE_OAUTH_TOKEN` (RO) without persisting it into qcow2
- A hand-written Codex sandbox can consume a writable `auth.json` mount and refresh tokens in place
- Manual `qemu-img create -f qcow2 -F qcow2` fork demo, including fresh deploy key + fresh Happy session identity for the child

**M2 — Launcher MVP**
- Phoenix app skeleton + SQLite + Caddy/Authentik integration
- Launcher dev workflow includes Mix checks plus a Rodney browser smoke test of the dashboard/create/detail flow.
- Application-level Authentik identity and `sandbox-admins` authorization,
  audited create attribution, and a loopback-only hardened launcher service
- Opaque server-generated credential UUIDs and path-free rendered sandbox
  functions; browser/API requests never accept host credential paths
- Socket-activated Go lifecycle broker with strict typed protocol, Unix peer
  authentication, root-owned per-sandbox locking, UUID-only credential
  resolution beneath a fixed staging root, and broker contract/adversarial tests
- Register repo flow with GitLab service-account OAuth and coding-agent picker (auth mode is implicit per agent)
- Broker-mediated, launcher-guided `claude setup-token` and `codex login`
  flows, stored per sandbox while exposing only opaque credential UUIDs to
  Phoenix
- Broker-generated per-sandbox SSH private keys; launcher registers only their
  public keys with GitLab
- Broker materializes the path-free microVM definition and performs fixed
  create/start/stop/status operations; Phoenix never writes the microVM tree or
  receives systemd, KVM, sudo, or host-filesystem privileges
- Proven stop ordering for writable Codex auth: stop VM, validate/persist
  refresh, then report success; quarantine and surface failures
- Dedicated Sandcastle systemd slice, maximum-two initial concurrency, bounded
  logs/storage, and explicit host/LAN/lateral network denies
- Live dashboard with VM status, Happy session status, restart session, stop/delete, chain-depth display

**M3 — Forking + devenv UX**
- "Fork" button (qcow2 backing-file with `-F qcow2`), with chain-depth flatten action
- devenv.nix detection + UI template editor
- Deploy key rotation timer (with scheduled restarts)
- `codex-auth-persist.service` round-trip on stop
- Branch protection helper button (including `code_owner_approval_required`)

**M4 — Happy relay module + end-to-end**
- Relay module shipped from this repo, configured with `SEED` from sops
- Mobile app pointed at self-hosted relay
- Full flow: register repo → pick agent → boot VM → drive from phone → fork with independent Happy session and independent OAuth credential
- v2 candidates queued: API-key fallback modes, Project Access Token Git auth, optional forward proxy for SNI-aware allowlisting, GitHub support

## 15. Glossary

- **Sandbox** — one microvm.nix VM dedicated to one repo (or one fork of one).
- **Base image** — the read-only NixOS closure used as the sandbox root.
- **Curated sandbox store** — the single host-side chroot store (`/var/lib/agent-sandcastle/store`) populated from explicit closure roots: VM toplevels, enabled agent/Happy packages, and the required microvm runner closures. It is served through a tagged literal `/nix/store` virtiofs source whose daemon sees a private bind mount of the curated store; the guest mounts that share at `/nix/.ro-store` and microvm.nix binds or overlays it into `/nix/store`. The host's main `/nix/store` is never exposed to sandboxes.
- **Launcher** — the web app that orchestrates everything.
- **Lifecycle broker** — the socket-activated, root-owned Go helper that
  resolves opaque credential UUIDs, owns VM filesystem mutations, and performs
  only allowlisted lifecycle operations. It handles one request per process and
  is not a general-purpose root daemon.
- **Credential ID** — a server-generated opaque UUID stored by the launcher.
  Only the broker may resolve it beneath the fixed credential staging root.
- **Relay** — the self-hosted Happy server that forwards encrypted mobile↔sandbox traffic.
- **Agent profile** — an allowlisted launcher entry mapping a UI choice (`claude-code`, `codex`) to a concrete VM command and required OAuth credential surface.
- **Agent auth mode** — the credential strategy for the selected agent; v1 is OAuth-only: `claude-oauth-token` for Claude, `codex-chatgpt-oauth` for Codex.
- **Claude Code OAuth token** — per-sandbox `sk-ant-oat01-…` token generated by `claude setup-token`, tied to the user's Claude.ai subscription, stored via sops, and mounted read-only into `happy-session.service`.
- **Codex ChatGPT auth.json** — per-sandbox OAuth credential generated by `codex login`, tied to the user's ChatGPT account, mounted writable so Codex can refresh tokens in place; persisted back into sops on VM stop.
- **Happy session** — the VM-side Happy CLI process that connects to the relay and runs the selected agent in the sandbox repo.
- **Fork** — a new sandbox whose qcow2 disk is a child of an existing sandbox's qcow2 (COW); always gets fresh deploy key, fresh agent OAuth credential, and fresh Happy session.
- **GitLab OAuth grant** — host-side OAuth refresh credential held by the launcher for the connected GitLab service account.
- **Sandbox deploy key** — per-sandbox SSH key enabled as a GitLab project deploy key for exactly one repo, owned by the GitLab service account.
