defmodule AgentSandcastleLauncher.DataCase do
  use ExUnit.CaseTemplate

  using do
    quote do
      alias AgentSandcastleLauncher.Repo

      import Ecto
      import Ecto.Changeset
      import Ecto.Query
      import AgentSandcastleLauncher.DataCase
    end
  end

  setup tags do
    AgentSandcastleLauncher.DataCase.setup_sandbox(tags)
    :ok
  end

  def setup_sandbox(tags) do
    pid =
      Ecto.Adapters.SQL.Sandbox.start_owner!(AgentSandcastleLauncher.Repo,
        shared: not tags[:async]
      )

    on_exit(fn -> Ecto.Adapters.SQL.Sandbox.stop_owner(pid) end)
  end
end
