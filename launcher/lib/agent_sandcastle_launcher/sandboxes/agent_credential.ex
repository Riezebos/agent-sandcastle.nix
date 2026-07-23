defmodule AgentSandcastleLauncher.Sandboxes.AgentCredential do
  use Ecto.Schema
  import Ecto.Changeset

  schema "agent_credentials" do
    field :agent_key, :string
    field :auth_mode, :string
    field :credential_id, Ecto.UUID
    field :writable, :boolean, default: false
    field :last_persisted_at, :utc_datetime_usec
    field :expires_at, :utc_datetime_usec
    field :revoked_at, :utc_datetime_usec

    belongs_to :sandbox, AgentSandcastleLauncher.Sandboxes.Sandbox

    timestamps(type: :utc_datetime_usec)
  end

  def changeset(credential, attrs) do
    credential
    |> cast(attrs, [
      :sandbox_id,
      :agent_key,
      :auth_mode,
      :credential_id,
      :writable,
      :last_persisted_at,
      :expires_at,
      :revoked_at
    ])
    |> validate_required([:sandbox_id, :agent_key, :auth_mode, :credential_id, :writable])
    |> unique_constraint(:credential_id)
    |> foreign_key_constraint(:sandbox_id)
  end
end
