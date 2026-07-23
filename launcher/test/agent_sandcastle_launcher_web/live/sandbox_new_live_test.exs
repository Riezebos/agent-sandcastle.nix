defmodule AgentSandcastleLauncherWeb.SandboxNewLiveTest do
  use AgentSandcastleLauncherWeb.ConnCase, async: true

  import Ecto.Query

  alias AgentSandcastleLauncher.Audit.Event

  test "creates an attributed dry run without accepting a host path", %{conn: conn} do
    {:ok, view, html} = live(conn, ~p"/sandboxes/new")

    refute html =~ "credential_path"
    refute html =~ "Staged Credential Path"

    view
    |> form("#sandbox-form",
      sandbox_request: %{
        repo_url: "git@gitlab.example.com:group/live-view-test.git",
        branch: "main",
        agent_key: "codex"
      }
    )
    |> render_submit()

    assert {path, _flash} = assert_redirect(view)
    assert path =~ ~r{^/sandboxes/\d+$}

    event =
      Event
      |> where([event], event.action == "sandbox.create_dry_run")
      |> Repo.one!()

    assert event.actor == "local-development"
    assert {:ok, _credential_id} = Ecto.UUID.cast(event.payload["credential_id"])
  end
end
