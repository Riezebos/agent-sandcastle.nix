defmodule AgentSandcastleLauncher.Sandboxes.Sandbox do
  use Ecto.Schema
  import Ecto.Changeset

  schema "sandboxes" do
    field :name, :string
    field :repo_url, :string
    field :branch, :string
    field :agent_key, :string
    field :agent_command, :string
    field :agent_auth_mode, :string
    field :happy_session_name, :string
    field :qcow2_path, :string
    field :status, :string, default: "dry_run"
    field :rendered_vm_spec, :string
    field :last_active_at, :utc_datetime_usec

    belongs_to :parent_sandbox, __MODULE__
    has_one :agent_credential, AgentSandcastleLauncher.Sandboxes.AgentCredential
    has_one :happy_session, AgentSandcastleLauncher.Sandboxes.HappySession

    timestamps(type: :utc_datetime_usec)
  end

  def changeset(sandbox, attrs) do
    sandbox
    |> cast(attrs, [
      :name,
      :repo_url,
      :branch,
      :agent_key,
      :agent_command,
      :agent_auth_mode,
      :happy_session_name,
      :qcow2_path,
      :status,
      :rendered_vm_spec,
      :parent_sandbox_id,
      :last_active_at
    ])
    |> validate_required([
      :name,
      :repo_url,
      :branch,
      :agent_key,
      :agent_command,
      :agent_auth_mode,
      :happy_session_name,
      :qcow2_path,
      :status,
      :rendered_vm_spec
    ])
    |> unique_constraint(:name)
  end
end
