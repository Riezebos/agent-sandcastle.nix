defmodule AgentSandcastleLauncherWeb.Plugs.AuthentikIdentity do
  @moduledoc """
  Establishes the application-level identity and admin authorization boundary.

  Production requests must carry identity headers copied by Caddy's Authentik
  `forward_auth` handler. The signed session copy is used only to attribute the
  LiveView connection; every initial HTTP request is authorized from its current
  proxy headers.
  """

  import Plug.Conn
  require Logger

  @username_header "x-authentik-username"
  @groups_header "x-authentik-groups"

  def init(opts), do: opts

  def call(conn, opts) do
    config = Application.get_env(:agent_sandcastle_launcher, :authentik, [])
    required? = Keyword.get(opts, :required, Keyword.get(config, :required, false))

    admin_group =
      Keyword.get(opts, :admin_group, Keyword.get(config, :admin_group, "sandbox-admins"))

    username = conn |> first_header(@username_header) |> normalize()
    groups = conn |> first_header(@groups_header) |> parse_groups()

    cond do
      not required? and is_nil(username) ->
        authorize(conn, "local-development", [admin_group])

      is_nil(username) ->
        reject(conn, 401, "Authentik identity is required")

      admin_group not in groups ->
        reject(conn, 403, "sandbox administrator access is required")

      true ->
        authorize(conn, username, groups)
    end
  end

  defp authorize(conn, username, groups) do
    identity = %{"username" => username, "groups" => groups}

    Logger.metadata(actor: username)

    conn
    |> put_private(:agent_sandcastle_identity, identity)
    |> put_session(:agent_sandcastle_identity, identity)
  end

  defp reject(conn, status, message) do
    conn
    |> put_resp_content_type("text/plain")
    |> send_resp(status, message)
    |> halt()
  end

  defp first_header(conn, name) do
    case get_req_header(conn, name) do
      [value | _] -> value
      [] -> nil
    end
  end

  defp normalize(value) when is_binary(value) do
    case String.trim(value) do
      "" -> nil
      normalized -> normalized
    end
  end

  defp normalize(_value), do: nil

  defp parse_groups(nil), do: []

  defp parse_groups(value) do
    value
    |> String.split(["|", ","], trim: true)
    |> Enum.map(&String.trim/1)
    |> Enum.reject(&(&1 == ""))
    |> Enum.uniq()
  end
end
