# Agent Sandcastle Launcher

Dry-run Phoenix LiveView scaffold for M2-pre. It records sandbox requests in
SQLite, resolves a read-only agent profile, and renders the intended
`mkSandbox` VM config without starting systemd or microVM units.

Local run target once the Beam toolchain is available:

```sh
nix develop .#launcher
cd launcher
mix setup
mix phx.server
```

Run `nix develop .#launcher` from the repository root so Hex/Mix caches stay in
ignored repo-local directories. Rodney session state is written under ignored
`.rodney/`; Rodney's browser downloader may still use its own cache unless you
start the Nix-provided Chromium manually and use `rodney connect`. The app
stores dev data in `priv/dev.db`.
Production defaults to `/var/lib/agent-sandcastle/state.db` through
`LAUNCHER_DATABASE_PATH`.

Frontend smoke test with Rodney:

```sh
nix develop .#launcher
cd launcher
mix setup
PORT=4001 mix phx.server
```

In another shell from the repo root:

```sh
rodney start --local
rodney open http://127.0.0.1:4001/
rodney assert 'document.title' 'Agent Sandcastle'
rodney assert 'document.querySelector("[data-phx-main]").classList.contains("phx-connected")'
```

Then drive the create flow with Rodney: open `/sandboxes/new`, fill repo URL,
branch, agent, and credential path sequentially, submit, and assert that the
detail page renders the expected `mkSandbox` auth fields. Keep field entry
sequential; parallel input commands can race LiveView validation patches.
