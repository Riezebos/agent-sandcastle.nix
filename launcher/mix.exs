defmodule AgentSandcastleLauncher.MixProject do
  use Mix.Project

  def project do
    [
      app: :agent_sandcastle_launcher,
      version: "0.1.0",
      elixir: "~> 1.17",
      elixirc_paths: elixirc_paths(Mix.env()),
      listeners: [Phoenix.CodeReloader],
      start_permanent: Mix.env() == :prod,
      aliases: aliases(),
      deps: deps(),
      releases: releases()
    ]
  end

  defp releases do
    [
      agent_sandcastle_launcher: [
        include_executables_for: [:unix],
        applications: [agent_sandcastle_launcher: :permanent]
      ]
    ]
  end

  def application do
    [
      mod: {AgentSandcastleLauncher.Application, []},
      extra_applications: [:crypto, :logger, :runtime_tools]
    ]
  end

  defp elixirc_paths(:test), do: ["lib", "test/support"]
  defp elixirc_paths(_), do: ["lib"]

  defp deps do
    [
      {:bandit, "~> 1.6"},
      {:ecto_sql, "~> 3.12"},
      {:ecto_sqlite3, "~> 0.20"},
      {:jason, "~> 1.4"},
      {:phoenix, "~> 1.7"},
      {:phoenix_ecto, "~> 4.6"},
      {:phoenix_html, "~> 4.1"},
      {:phoenix_live_reload, "~> 1.5", only: :dev},
      {:phoenix_live_view, "~> 1.0"},
      {:telemetry_metrics, "~> 1.0"},
      {:telemetry_poller, "~> 1.0"}
    ]
  end

  defp aliases do
    [
      setup: ["deps.get", "ecto.setup"],
      "ecto.setup": ["ecto.create", "ecto.migrate"],
      "ecto.reset": ["ecto.drop", "ecto.setup"],
      test: ["ecto.create --quiet", "ecto.migrate --quiet", "test"]
    ]
  end
end
