defmodule AgentSandcastleLauncher.Sandboxes.HappySession do
  use Ecto.Schema
  import Ecto.Changeset

  schema "happy_sessions" do
    field :relay_url, :string
    field :session_name, :string
    field :status, :string, default: "planned"
    field :state_reset_at, :utc_datetime_usec
    field :last_seen_at, :utc_datetime_usec

    belongs_to :sandbox, AgentSandcastleLauncher.Sandboxes.Sandbox

    timestamps(type: :utc_datetime_usec)
  end

  def changeset(session, attrs) do
    session
    |> cast(attrs, [
      :sandbox_id,
      :relay_url,
      :session_name,
      :status,
      :state_reset_at,
      :last_seen_at
    ])
    |> validate_required([:sandbox_id, :relay_url, :session_name, :status])
    |> foreign_key_constraint(:sandbox_id)
  end
end
