defmodule AgentSandcastleLauncher.Agents.Registry do
  @moduledoc """
  Read-only registry of agent profiles the dry-run launcher can render.
  """

  @agents [
    %{
      key: "claude-code",
      display_name: "Claude Code",
      command: ["claude"],
      auth_mode: "claude-oauth-token",
      credential_label: "Directory containing claude.env",
      writable: false
    },
    %{
      key: "codex",
      display_name: "Codex",
      command: ["codex"],
      auth_mode: "codex-chatgpt-oauth",
      credential_label: "Directory containing writable auth.json",
      writable: true
    }
  ]

  def list, do: @agents

  def options do
    Enum.map(@agents, &{&1.display_name, &1.key})
  end

  def fetch(key) do
    case Enum.find(@agents, &(&1.key == key)) do
      nil -> :error
      agent -> {:ok, agent}
    end
  end

  def fetch!(key) do
    case fetch(key) do
      {:ok, agent} -> agent
      :error -> raise ArgumentError, "unknown agent key: #{inspect(key)}"
    end
  end

  def valid_key?(key) do
    match?({:ok, _agent}, fetch(key))
  end
end
