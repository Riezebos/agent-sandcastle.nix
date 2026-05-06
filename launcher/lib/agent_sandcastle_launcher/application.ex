defmodule AgentSandcastleLauncher.Application do
  @moduledoc false

  use Application

  @impl true
  def start(_type, _args) do
    children = [
      AgentSandcastleLauncher.Repo,
      {Phoenix.PubSub, name: AgentSandcastleLauncher.PubSub},
      AgentSandcastleLauncherWeb.Endpoint
    ]

    opts = [strategy: :one_for_one, name: AgentSandcastleLauncher.Supervisor]
    Supervisor.start_link(children, opts)
  end

  @impl true
  def config_change(changed, _new, removed) do
    AgentSandcastleLauncherWeb.Endpoint.config_change(changed, removed)
    :ok
  end
end
