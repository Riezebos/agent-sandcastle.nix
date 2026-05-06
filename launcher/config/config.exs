import Config

config :agent_sandcastle_launcher,
  ecto_repos: [AgentSandcastleLauncher.Repo],
  generators: [timestamp_type: :utc_datetime_usec]

config :agent_sandcastle_launcher, AgentSandcastleLauncherWeb.Endpoint,
  url: [host: "localhost"],
  adapter: Bandit.PhoenixAdapter,
  render_errors: [
    formats: [html: AgentSandcastleLauncherWeb.ErrorHTML],
    layout: false
  ],
  pubsub_server: AgentSandcastleLauncher.PubSub,
  live_view: [signing_salt: "agent-sandcastle-dry-run"]

config :logger, :default_formatter,
  format: "$time $metadata[$level] $message\n",
  metadata: [:request_id]

import_config "#{config_env()}.exs"
