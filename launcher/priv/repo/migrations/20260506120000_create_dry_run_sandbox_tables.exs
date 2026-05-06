defmodule AgentSandcastleLauncher.Repo.Migrations.CreateDryRunSandboxTables do
  use Ecto.Migration

  def change do
    create table(:sandboxes) do
      add :name, :text, null: false
      add :repo_url, :text, null: false
      add :branch, :text, null: false
      add :parent_sandbox_id, references(:sandboxes, on_delete: :restrict)
      add :agent_key, :text, null: false
      add :agent_command, :text, null: false
      add :agent_auth_mode, :text, null: false
      add :happy_session_name, :text, null: false
      add :qcow2_path, :text, null: false
      add :status, :text, null: false
      add :rendered_vm_spec, :text, null: false
      add :last_active_at, :utc_datetime_usec

      timestamps(type: :utc_datetime_usec)
    end

    create unique_index(:sandboxes, [:name])
    create index(:sandboxes, [:status])
    create index(:sandboxes, [:agent_key])

    create table(:agent_credentials) do
      add :sandbox_id, references(:sandboxes, on_delete: :delete_all), null: false
      add :agent_key, :text, null: false
      add :auth_mode, :text, null: false
      add :staged_path, :text, null: false
      add :writable, :boolean, null: false, default: false
      add :last_persisted_at, :utc_datetime_usec
      add :expires_at, :utc_datetime_usec
      add :revoked_at, :utc_datetime_usec

      timestamps(type: :utc_datetime_usec)
    end

    create index(:agent_credentials, [:sandbox_id])
    create index(:agent_credentials, [:agent_key])

    create table(:happy_sessions) do
      add :sandbox_id, references(:sandboxes, on_delete: :delete_all), null: false
      add :relay_url, :text, null: false
      add :session_name, :text, null: false
      add :status, :text, null: false
      add :state_reset_at, :utc_datetime_usec
      add :last_seen_at, :utc_datetime_usec

      timestamps(type: :utc_datetime_usec)
    end

    create unique_index(:happy_sessions, [:session_name])
    create index(:happy_sessions, [:sandbox_id])
  end
end
