defmodule AgentSandcastleLauncher.SandboxesTest do
  use AgentSandcastleLauncher.DataCase, async: true

  alias AgentSandcastleLauncher.Sandboxes

  test "create_sandbox stores a dry-run spec for claude" do
    assert {:ok, sandbox} =
             Sandboxes.create_sandbox(%{
               "repo_url" => "git@gitlab.example.com:group/project.git",
               "branch" => "main",
               "agent_key" => "claude-code",
               "credential_path" => "/var/lib/agent-sandcastle/example-credentials/claude-demo"
             })

    assert sandbox.status == "dry_run"
    assert sandbox.agent_auth_mode == "claude-oauth-token"
    assert sandbox.rendered_vm_spec =~ "agentSecretsSource"
    assert sandbox.happy_session.session_name == sandbox.happy_session_name
  end
end
