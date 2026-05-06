import Config

config :agent_sandcastle_launcher, AgentSandcastleLauncher.Repo,
  database: Path.expand("../priv/test.db", __DIR__),
  pool: Ecto.Adapters.SQL.Sandbox,
  pool_size: 5

config :agent_sandcastle_launcher, AgentSandcastleLauncherWeb.Endpoint,
  http: [ip: {127, 0, 0, 1}, port: 4002],
  server: false,
  secret_key_base:
    "test-only-agent-sandcastle-launcher-secret-key-base-64-plus-bytes-for-cookie-session-signing"

config :logger, level: :warning
config :phoenix, :plug_init_mode, :runtime
