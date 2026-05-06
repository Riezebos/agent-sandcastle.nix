{ agent-sandcastle }:

{ config, lib, ... }:

let
  credentialRoot = "/var/lib/agent-sandcastle/example-credentials";

  mkAgentSandbox =
    { name
    , agentKey
    , agentCommand
    , agentAuthMode
    , authConfig
    }:
    agent-sandcastle.lib.mkSandbox ({
      inherit name agentKey agentCommand agentAuthMode;

      repoUrl = "git@gitlab.example.com:group/project.git";
      branch = "main";
      networkMode = "tap";
      useCuratedStore = true;
      happyRelayUrl = "https://happy.example.com";
      happySessionName = name;
    } // authConfig);

  vmClosureRoots = vmName: [
    config.microvm.vms.${vmName}.config.config.system.build.toplevel
    config.microvm.vms.${vmName}.config.config.microvm.declaredRunner
  ];
in
{
  services.agent-sandcastle.sandboxStore = {
    enable = true;
    closureRoots =
      vmClosureRoots "claude-demo"
      ++ vmClosureRoots "codex-demo";
  };

  services.agent-sandcastle.networking = {
    enable = true;
    allowedHostnames = lib.mkBefore [
      "gitlab.example.com"
      "happy.example.com"
    ];
  };

  microvm.vms.claude-demo = {
    autostart = false;
    config = mkAgentSandbox {
      name = "claude-demo";
      agentKey = "claude-code";
      agentCommand = [ "claude" ];
      agentAuthMode = "claude-oauth-token";
      authConfig = {
        agentSecretsSource = "${credentialRoot}/claude-demo";
        claudeEnvironmentFile = "/run/agent-sandcastle/secrets/claude.env";
      };
    };
  };

  microvm.vms.codex-demo = {
    autostart = false;
    config = mkAgentSandbox {
      name = "codex-demo";
      agentKey = "codex";
      agentCommand = [ "codex" ];
      agentAuthMode = "codex-chatgpt-oauth";
      authConfig = {
        codexAuthSource = "${credentialRoot}/codex-demo";
        codexAuthJson = "/run/agent-sandcastle/codex-auth/auth.json";
      };
    };
  };
}
