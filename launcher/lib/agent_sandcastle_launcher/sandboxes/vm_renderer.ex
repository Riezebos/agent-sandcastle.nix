defmodule AgentSandcastleLauncher.Sandboxes.VmRenderer do
  @moduledoc """
  Renders a path-free microVM config function for dry-run records.

  Credential IDs and host paths deliberately never enter this renderer. The
  trusted host broker must resolve an opaque credential ID beneath its fixed
  staging root and pass the resulting `credentialSource` path when it evaluates
  this function.
  """

  def render(params, agent) do
    auth_lines =
      case agent.auth_mode do
        "claude-oauth-token" ->
          [
            {"agentSecretsSource", :credential_source},
            {"claudeEnvironmentFile", "/run/agent-sandcastle/secrets/claude.env"}
          ]

        "codex-chatgpt-oauth" ->
          [
            {"codexAuthSource", :credential_source},
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
    { credentialSource }:
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
      "  #{key} = #{nix_value(value)};"
    end)
  end

  defp nix_value(:credential_source), do: "credentialSource"
  defp nix_value(value), do: nix_string(value)

  defp nix_list(values) do
    "[ " <> Enum.map_join(values, " ", &nix_string/1) <> " ]"
  end

  defp nix_string(value) when is_binary(value) do
    escaped =
      value
      |> String.replace("\\", "\\\\")
      |> String.replace("\"", "\\\"")
      |> String.replace("${", "\\${")
      |> String.replace("\n", "\\n")
      |> String.replace("\r", "\\r")
      |> String.replace("\t", "\\t")

    "\"#{escaped}\""
  end
end
