defmodule AgentSandcastleLauncher.SandboxesTest do
  use AgentSandcastleLauncher.DataCase, async: true

  alias AgentSandcastleLauncher.Sandboxes
  alias AgentSandcastleLauncher.Audit.Event
  alias AgentSandcastleLauncher.Repo

  test "create_sandbox stores a path-free dry-run spec and attributed audit event for claude" do
    assert {:ok, sandbox} =
             Sandboxes.create_sandbox(
               %{
                 "repo_url" => "git@gitlab.example.com:group/project.git",
                 "branch" => "main",
                 "agent_key" => "claude-code"
               },
               "alice"
             )

    assert sandbox.status == "dry_run"
    assert sandbox.agent_auth_mode == "claude-oauth-token"
    assert {:ok, _credential_id} = Ecto.UUID.cast(sandbox.agent_credential.credential_id)
    assert sandbox.rendered_vm_spec =~ "{ credentialSource }:"
    assert sandbox.rendered_vm_spec =~ "agentSecretsSource"
    refute sandbox.rendered_vm_spec =~ sandbox.agent_credential.credential_id
    refute sandbox.rendered_vm_spec =~ "/var/lib/agent-sandcastle"
    assert sandbox.happy_session.session_name == sandbox.happy_session_name

    event = Repo.get_by!(Event, sandbox_id: sandbox.id, action: "sandbox.create_dry_run")
    assert event.actor == "alice"
    assert event.payload["credential_id"] == sandbox.agent_credential.credential_id
  end

  test "create_sandbox renders codex with a broker-supplied credential source" do
    assert {:ok, sandbox} =
             Sandboxes.create_sandbox(
               %{
                 "repo_url" => "https://gitlab.example.com/group/codex-project.git",
                 "branch" => "feature/auth",
                 "agent_key" => "codex"
               },
               "bob"
             )

    assert sandbox.agent_auth_mode == "codex-chatgpt-oauth"
    assert sandbox.agent_credential.writable
    assert sandbox.rendered_vm_spec =~ "codexAuthSource = credentialSource;"
    refute sandbox.rendered_vm_spec =~ "agentSecretsSource"
  end

  test "credential_path input is ignored rather than becoming a host mount" do
    assert {:ok, sandbox} =
             Sandboxes.create_sandbox(
               %{
                 "repo_url" => "git@gitlab.example.com:group/project.git",
                 "agent_key" => "claude-code",
                 "credential_path" => "/etc"
               },
               "alice"
             )

    refute sandbox.rendered_vm_spec =~ "/etc"
    refute Map.has_key?(sandbox.agent_credential, :staged_path)
  end
end
