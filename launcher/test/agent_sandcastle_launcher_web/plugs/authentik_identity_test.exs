defmodule AgentSandcastleLauncherWeb.Plugs.AuthentikIdentityTest do
  use ExUnit.Case, async: true

  import Plug.Conn
  import Plug.Test

  alias AgentSandcastleLauncherWeb.Plugs.AuthentikIdentity

  test "rejects a missing production identity" do
    conn =
      conn(:get, "/")
      |> init_test_session(%{})
      |> AuthentikIdentity.call(required: true, admin_group: "sandbox-admins")

    assert conn.halted
    assert conn.status == 401
  end

  test "rejects an authenticated user outside the admin group" do
    conn =
      conn(:get, "/")
      |> put_req_header("x-authentik-username", "alice")
      |> put_req_header("x-authentik-groups", "developers|sandbox-users")
      |> init_test_session(%{})
      |> AuthentikIdentity.call(required: true, admin_group: "sandbox-admins")

    assert conn.halted
    assert conn.status == 403
  end

  test "stores an attributed identity for an authorized user" do
    conn =
      conn(:get, "/")
      |> put_req_header("x-authentik-username", "alice")
      |> put_req_header("x-authentik-groups", "developers|sandbox-admins")
      |> init_test_session(%{})
      |> AuthentikIdentity.call(required: true, admin_group: "sandbox-admins")

    refute conn.halted

    assert get_session(conn, :agent_sandcastle_identity) == %{
             "username" => "alice",
             "groups" => ["developers", "sandbox-admins"]
           }
  end

  test "uses an explicit local identity only when authorization is disabled" do
    conn =
      conn(:get, "/")
      |> init_test_session(%{})
      |> AuthentikIdentity.call(required: false, admin_group: "sandbox-admins")

    refute conn.halted
    assert get_session(conn, :agent_sandcastle_identity)["username"] == "local-development"
  end
end
