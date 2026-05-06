defmodule AgentSandcastleLauncher.Sandboxes.SandboxRequest do
  use Ecto.Schema
  import Ecto.Changeset

  alias AgentSandcastleLauncher.Agents.Registry

  @primary_key false
  embedded_schema do
    field :repo_url, :string
    field :branch, :string, default: "main"
    field :agent_key, :string, default: "claude-code"
    field :credential_path, :string
  end

  def changeset(request, attrs) do
    request
    |> cast(attrs, [:repo_url, :branch, :agent_key, :credential_path])
    |> update_change(:repo_url, &trim/1)
    |> update_change(:branch, &trim/1)
    |> update_change(:credential_path, &trim/1)
    |> validate_required([:repo_url, :branch, :agent_key, :credential_path])
    |> validate_change(:agent_key, fn :agent_key, key ->
      if Registry.valid_key?(key), do: [], else: [agent_key: "is not enabled"]
    end)
  end

  defp trim(value) when is_binary(value), do: String.trim(value)
  defp trim(value), do: value
end
