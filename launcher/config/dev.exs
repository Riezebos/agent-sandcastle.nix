import Config

config :agent_sandcastle_launcher, AgentSandcastleLauncher.Repo,
  database: Path.expand("../priv/dev.db", __DIR__),
  pool_size: 5,
  stacktrace: true,
  show_sensitive_data_on_connection_error: true

config :agent_sandcastle_launcher, AgentSandcastleLauncherWeb.Endpoint,
  http: [ip: {127, 0, 0, 1}, port: String.to_integer(System.get_env("PORT") || "4000")],
  check_origin: false,
  code_reloader: true,
  debug_errors: true,
  secret_key_base:
    "dev-only-agent-sandcastle-launcher-secret-key-base-64-plus-bytes-for-cookie-session-signing"

config :phoenix, :plug_init_mode, :runtime
