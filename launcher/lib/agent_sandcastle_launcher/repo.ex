defmodule AgentSandcastleLauncher.Repo do
  use Ecto.Repo,
    otp_app: :agent_sandcastle_launcher,
    adapter: Ecto.Adapters.SQLite3
end
