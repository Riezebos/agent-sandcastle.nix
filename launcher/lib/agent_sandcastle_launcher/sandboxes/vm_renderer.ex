defmodule AgentSandcastleLauncher.Sandboxes.VmRenderer do
  @moduledoc """
  Renders the intended microVM config for dry-run records.
  """

  def render(params, agent) do
    auth_lines =
      case agent.auth_mode do
        "claude-oauth-token" ->
          [
            {"agentSecretsSource", params.credential_path},
            {"claudeEnvironmentFile", "/run/agent-sandcastle/secrets/claude.env"}
          ]

        "codex-chatgpt-oauth" ->
          [
            {"codexAuthSource", params.credential_path},
            {"codexAuthJson", "/run/agent-sandcastle/codex-auth/auth.json"}
          ]
      end

    vm_params = %{
      name: params.name,
      repo_url: params.repo_url,
      branch: params.branch,
      agent_key: agent.key,
      agent_command: agent.command,
      agent_auth_mode: agent.auth_mode,
      happy_relay_url: params.happy_relay_url,
      happy_session_name: params.happy_session_name,
      qcow2_path: params.qcow2_path,
      network_mode: "tap",
      use_curated_store: true
    }

    spec = """
    agent-sandcastle.lib.mkSandbox {
      name = #{nix_string(params.name)};
      repoUrl = #{nix_string(params.repo_url)};
      branch = #{nix_string(params.branch)};
      agentKey = #{nix_string(agent.key)};
      agentCommand = #{nix_list(agent.command)};
      agentAuthMode = #{nix_string(agent.auth_mode)};
      happyRelayUrl = #{nix_string(params.happy_relay_url)};
      happySessionName = #{nix_string(params.happy_session_name)};
      networkMode = "tap";
      useCuratedStore = true;
    #{render_auth(auth_lines)}
    }
    """

    {vm_params, spec}
  end

  defp render_auth(lines) do
    Enum.map_join(lines, "\n", fn {key, value} ->
      "  #{key} = #{nix_string(value)};"
    end)
  end

  defp nix_list(values) do
    "[ " <> Enum.map_join(values, " ", &nix_string/1) <> " ]"
  end

  defp nix_string(value), do: inspect(value)
end
