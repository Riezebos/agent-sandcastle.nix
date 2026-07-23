defmodule AgentSandcastleLauncherWeb.ConnCase do
  use ExUnit.CaseTemplate

  using do
    quote do
      @endpoint AgentSandcastleLauncherWeb.Endpoint

      use AgentSandcastleLauncherWeb, :verified_routes

      import Phoenix.ConnTest
      import Phoenix.LiveViewTest

      alias AgentSandcastleLauncher.Repo

      @moduletag :web
    end
  end

  setup tags do
    AgentSandcastleLauncher.DataCase.setup_sandbox(tags)
    {:ok, conn: Phoenix.ConnTest.build_conn()}
  end
end
