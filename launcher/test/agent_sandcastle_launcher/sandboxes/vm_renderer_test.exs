defmodule AgentSandcastleLauncher.Sandboxes.VmRendererTest do
  use ExUnit.Case, async: true

  alias AgentSandcastleLauncher.Agents.Registry
  alias AgentSandcastleLauncher.Sandboxes.VmRenderer

  test "escapes Nix interpolation, quotes, backslashes, and newlines" do
    params = %{
      name: "safe-name",
      repo_url: "https://example.test/${builtins.abort \"boom\"}\\repo\nnext",
      branch: "main",
      happy_relay_url: "https://happy.example.test",
      happy_session_name: "safe-session",
      qcow2_path: "/var/lib/agent-sandcastle/disks/safe.qcow2"
    }

    {_vm_params, spec} = VmRenderer.render(params, Registry.fetch!("claude-code"))

    assert spec =~ ~S(\${builtins.abort \"boom\"}\\repo\nnext)
    refute spec =~ ~S("${builtins.abort)
  end

  test "never accepts or renders a credential identifier or source path" do
    params = %{
      name: "safe-name",
      repo_url: "https://example.test/repo.git",
      branch: "main",
      credential_id: Ecto.UUID.generate(),
      credential_path: "/etc",
      happy_relay_url: "https://happy.example.test",
      happy_session_name: "safe-session",
      qcow2_path: "/var/lib/agent-sandcastle/disks/safe.qcow2"
    }

    {_vm_params, spec} = VmRenderer.render(params, Registry.fetch!("codex"))

    assert spec =~ "{ credentialSource }:"
    assert spec =~ "codexAuthSource = credentialSource;"
    refute spec =~ params.credential_id
    refute spec =~ params.credential_path
  end
end
