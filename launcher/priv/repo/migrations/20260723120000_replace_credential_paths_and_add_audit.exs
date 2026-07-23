defmodule AgentSandcastleLauncher.Repo.Migrations.ReplaceCredentialPathsAndAddAudit do
  use Ecto.Migration

  def up do
    alter table(:agent_credentials) do
      add :credential_id, :text
    end

    execute("""
    UPDATE agent_credentials
    SET credential_id =
      lower(
        substr(hex(randomblob(16)), 1, 8) || '-' ||
        substr(hex(randomblob(16)), 1, 4) || '-4' ||
        substr(hex(randomblob(16)), 1, 3) || '-a' ||
        substr(hex(randomblob(16)), 1, 3) || '-' ||
        substr(hex(randomblob(16)), 1, 12)
      )
    WHERE credential_id IS NULL
    """)

    # ecto_sqlite3 intentionally rejects ALTER COLUMN. Rebuild this small
    # metadata table so the database itself enforces the new NOT NULL shape
    # and the legacy host-path column is physically removed.
    execute("""
    CREATE TABLE agent_credentials_opaque (
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      sandbox_id INTEGER NOT NULL REFERENCES sandboxes(id) ON DELETE CASCADE,
      agent_key TEXT NOT NULL,
      auth_mode TEXT NOT NULL,
      credential_id TEXT NOT NULL,
      writable INTEGER NOT NULL DEFAULT 0,
      last_persisted_at TEXT,
      expires_at TEXT,
      revoked_at TEXT,
      inserted_at TEXT NOT NULL,
      updated_at TEXT NOT NULL
    )
    """)

    execute("""
    INSERT INTO agent_credentials_opaque (
      id, sandbox_id, agent_key, auth_mode, credential_id, writable,
      last_persisted_at, expires_at, revoked_at, inserted_at, updated_at
    )
    SELECT
      id, sandbox_id, agent_key, auth_mode, credential_id, writable,
      last_persisted_at, expires_at, revoked_at, inserted_at, updated_at
    FROM agent_credentials
    """)

    drop table(:agent_credentials)
    rename table(:agent_credentials_opaque), to: table(:agent_credentials)

    create unique_index(:agent_credentials, [:credential_id])
    create index(:agent_credentials, [:sandbox_id])
    create index(:agent_credentials, [:agent_key])

    create table(:audit_events) do
      add :sandbox_id, references(:sandboxes, on_delete: :delete_all), null: false
      add :action, :text, null: false
      add :actor, :text, null: false
      add :payload, :map, null: false

      timestamps(type: :utc_datetime_usec, updated_at: false)
    end

    create index(:audit_events, [:sandbox_id])
    create index(:audit_events, [:actor])
    create index(:audit_events, [:action])
  end

  def down do
    drop table(:audit_events)

    execute("""
    CREATE TABLE agent_credentials_with_paths (
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      sandbox_id INTEGER NOT NULL REFERENCES sandboxes(id) ON DELETE CASCADE,
      agent_key TEXT NOT NULL,
      auth_mode TEXT NOT NULL,
      staged_path TEXT NOT NULL,
      writable INTEGER NOT NULL DEFAULT 0,
      last_persisted_at TEXT,
      expires_at TEXT,
      revoked_at TEXT,
      inserted_at TEXT NOT NULL,
      updated_at TEXT NOT NULL
    )
    """)

    execute("""
    INSERT INTO agent_credentials_with_paths (
      id, sandbox_id, agent_key, auth_mode, staged_path, writable,
      last_persisted_at, expires_at, revoked_at, inserted_at, updated_at
    )
    SELECT
      id, sandbox_id, agent_key, auth_mode,
      'removed-by-opaque-credential-id-migration', writable,
      last_persisted_at, expires_at, revoked_at, inserted_at, updated_at
    FROM agent_credentials
    """)

    drop table(:agent_credentials)
    rename table(:agent_credentials_with_paths), to: table(:agent_credentials)

    create index(:agent_credentials, [:sandbox_id])
    create index(:agent_credentials, [:agent_key])
  end
end
