defmodule AgentSandcastleLauncher.Release do
  @moduledoc """
  Helpers invoked from the release entrypoint to manage Ecto migrations.

  The launcher's NixOS module runs `bin/agent_sandcastle_launcher eval
  'AgentSandcastleLauncher.Release.migrate()'` in a `preStart` ExecStartPre,
  so the SQLite schema is reconciled before the web server boots.
  """

  @app :agent_sandcastle_launcher

  def migrate do
    load_app()

    for repo <- repos() do
      {:ok, _, _} = Ecto.Migrator.with_repo(repo, &Ecto.Migrator.run(&1, :up, all: true))
    end

    :ok
  end

  def rollback(repo, version) do
    load_app()
    {:ok, _, _} = Ecto.Migrator.with_repo(repo, &Ecto.Migrator.run(&1, :down, to: version))
    :ok
  end

  defp repos do
    Application.fetch_env!(@app, :ecto_repos)
  end

  defp load_app do
    Application.load(@app)
  end
end
