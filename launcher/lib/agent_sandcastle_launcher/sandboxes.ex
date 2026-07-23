defmodule AgentSandcastleLauncher.Sandboxes do
  @moduledoc """
  Dry-run sandbox records and rendered VM specs.
  """

  import Ecto.Query, warn: false

  alias Ecto.Multi
  alias AgentSandcastleLauncher.Agents.Registry
  alias AgentSandcastleLauncher.Audit.Event
  alias AgentSandcastleLauncher.Repo
  alias AgentSandcastleLauncher.Sandboxes.AgentCredential
  alias AgentSandcastleLauncher.Sandboxes.HappySession
  alias AgentSandcastleLauncher.Sandboxes.Sandbox
  alias AgentSandcastleLauncher.Sandboxes.SandboxRequest
  alias AgentSandcastleLauncher.Sandboxes.VmRenderer

  @happy_relay_url "https://happy.example.com"

  def list_sandboxes do
    Sandbox
    |> order_by([s], desc: s.inserted_at)
    |> preload([:agent_credential, :happy_session])
    |> Repo.all()
  end

  def get_sandbox!(id) do
    Sandbox
    |> preload([:agent_credential, :happy_session])
    |> Repo.get!(id)
  end

  def change_sandbox_request(attrs \\ %{}) do
    SandboxRequest.changeset(%SandboxRequest{}, attrs)
  end

  def create_sandbox(attrs, actor) when is_binary(actor) do
    changeset = change_sandbox_request(attrs)

    if changeset.valid? do
      request = Ecto.Changeset.apply_changes(changeset)
      agent = Registry.fetch!(request.agent_key)
      credential_id = Ecto.UUID.generate()
      name = sandbox_name(request.repo_url)
      happy_session_name = "#{name}-#{short_id()}"
      qcow2_path = "/var/lib/agent-sandcastle/disks/#{name}.qcow2"

      render_params = %{
        name: name,
        repo_url: request.repo_url,
        branch: request.branch,
        happy_relay_url: @happy_relay_url,
        happy_session_name: happy_session_name,
        qcow2_path: qcow2_path
      }

      {_vm_params, rendered_vm_spec} = VmRenderer.render(render_params, agent)

      Multi.new()
      |> Multi.insert(
        :sandbox,
        Sandbox.changeset(%Sandbox{}, %{
          name: name,
          repo_url: request.repo_url,
          branch: request.branch,
          agent_key: agent.key,
          agent_command: Enum.join(agent.command, " "),
          agent_auth_mode: agent.auth_mode,
          happy_session_name: happy_session_name,
          qcow2_path: qcow2_path,
          status: "dry_run",
          rendered_vm_spec: rendered_vm_spec
        })
      )
      |> Multi.insert(:agent_credential, fn %{sandbox: sandbox} ->
        AgentCredential.changeset(%AgentCredential{}, %{
          sandbox_id: sandbox.id,
          agent_key: agent.key,
          auth_mode: agent.auth_mode,
          credential_id: credential_id,
          writable: agent.writable
        })
      end)
      |> Multi.insert(:happy_session, fn %{sandbox: sandbox} ->
        HappySession.changeset(%HappySession{}, %{
          sandbox_id: sandbox.id,
          relay_url: @happy_relay_url,
          session_name: happy_session_name,
          status: "planned"
        })
      end)
      |> Multi.insert(:audit_event, fn %{sandbox: sandbox} ->
        Event.changeset(%Event{}, %{
          sandbox_id: sandbox.id,
          action: "sandbox.create_dry_run",
          actor: actor,
          payload: %{
            "agent_key" => agent.key,
            "branch" => request.branch,
            "credential_id" => credential_id,
            "repo_url" => request.repo_url
          }
        })
      end)
      |> Repo.transaction()
      |> case do
        {:ok, %{sandbox: sandbox}} -> {:ok, get_sandbox!(sandbox.id)}
        {:error, _step, failed_changeset, _changes} -> {:error, failed_changeset}
      end
    else
      {:error, %{changeset | action: :insert}}
    end
  end

  defp sandbox_name(repo_url) do
    slug =
      repo_url
      |> String.trim()
      |> String.split(["/", ":"], trim: true)
      |> repo_leaf()
      |> String.replace_suffix(".git", "")
      |> String.downcase()
      |> String.replace(~r/[^a-z0-9._-]+/, "-")
      |> String.trim("-")

    base = if slug == "", do: "sandbox", else: slug
    "#{base}-#{short_id()}"
  end

  defp repo_leaf(parts), do: List.last(parts) || "sandbox"

  defp short_id do
    4
    |> :crypto.strong_rand_bytes()
    |> Base.url_encode64(padding: false)
    |> String.downcase()
  end
end
