defmodule AgentSandcastleLauncher.Audit.Event do
  use Ecto.Schema
  import Ecto.Changeset

  schema "audit_events" do
    field :action, :string
    field :actor, :string
    field :payload, :map

    belongs_to :sandbox, AgentSandcastleLauncher.Sandboxes.Sandbox

    timestamps(type: :utc_datetime_usec, updated_at: false)
  end

  def changeset(event, attrs) do
    event
    |> cast(attrs, [:sandbox_id, :action, :actor, :payload])
    |> validate_required([:sandbox_id, :action, :actor, :payload])
    |> validate_length(:actor, min: 1, max: 255)
    |> foreign_key_constraint(:sandbox_id)
  end
end
