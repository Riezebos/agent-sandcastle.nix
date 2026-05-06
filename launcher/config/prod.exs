import Config

config :agent_sandcastle_launcher, AgentSandcastleLauncherWeb.Endpoint,
  cache_static_manifest: "priv/static/cache_manifest.json"

config :logger, level: :info
