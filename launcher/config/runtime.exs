import Config

if System.get_env("PHX_SERVER") == "true" do
  config :agent_sandcastle_launcher, AgentSandcastleLauncherWeb.Endpoint, server: true
end

if config_env() == :prod do
  database_path = System.get_env("LAUNCHER_DATABASE_PATH") || "/var/lib/agent-sandcastle/state.db"
  host = System.get_env("PHX_HOST") || "localhost"
  port = String.to_integer(System.get_env("PORT") || "4000")

  bind_addr =
    case System.get_env("PHX_HTTP_IP") do
      nil -> {127, 0, 0, 1}
      raw -> raw |> String.split(".") |> Enum.map(&String.to_integer/1) |> List.to_tuple()
    end

  authentik_required =
    System.get_env("AUTHENTIK_REQUIRED", "true")
    |> String.downcase()
    |> then(&(&1 in ["1", "true", "yes"]))

  config :agent_sandcastle_launcher, :authentik,
    required: authentik_required,
    admin_group: System.get_env("AUTHENTIK_ADMIN_GROUP", "sandbox-admins")

  config :agent_sandcastle_launcher, AgentSandcastleLauncher.Repo,
    database: database_path,
    pool_size: String.to_integer(System.get_env("POOL_SIZE") || "5")

  config :agent_sandcastle_launcher, AgentSandcastleLauncherWeb.Endpoint,
    http: [ip: bind_addr, port: port],
    url: [host: host, port: 443, scheme: "https"],
    secret_key_base: System.fetch_env!("SECRET_KEY_BASE")
end
