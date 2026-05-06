import Config

if config_env() == :prod do
  database_path = System.get_env("LAUNCHER_DATABASE_PATH") || "/var/lib/agent-sandcastle/state.db"
  host = System.get_env("PHX_HOST") || "localhost"
  port = String.to_integer(System.get_env("PORT") || "4000")

  config :agent_sandcastle_launcher, AgentSandcastleLauncher.Repo,
    database: database_path,
    pool_size: String.to_integer(System.get_env("POOL_SIZE") || "5")

  config :agent_sandcastle_launcher, AgentSandcastleLauncherWeb.Endpoint,
    http: [ip: {127, 0, 0, 1}, port: port],
    url: [host: host, port: 443, scheme: "https"],
    secret_key_base: System.fetch_env!("SECRET_KEY_BASE"),
    server: System.get_env("PHX_SERVER") == "true"
end
