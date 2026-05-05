{ lib }:

let
  validName = name:
    builtins.match "[A-Za-z0-9][A-Za-z0-9._-]*" name != null;

  macForName = name:
    let
      hash = builtins.hashString "sha256" name;
      octet = offset: builtins.substring offset 2 hash;
    in
    "02:00:${octet 0}:${octet 2}:${octet 4}:${octet 6}";
in
{
  mkSandbox =
    { name
    , repoUrl ? null
    , branch ? null
    , workdir ? "/home/dev/work"
    , agentKey ? "noop"
    , agentCommand ? [ ]
    , agentAuthMode ? "none"
    , happyRelayUrl ? "http://127.0.0.1:3005"
    , happySessionName ? name
    , authorizedKeys ? [ ]
    , sshHostPort ? null
    , vcpu ? 2
    , memoryMiB ? 2304
    , diskSizeMiB ? 4096
    }:
    { lib, pkgs, ... }:

    let
      repoUrlValue = if repoUrl == null then "" else repoUrl;
      branchValue = if branch == null then "" else branch;

      agentCommandLine =
        lib.concatMapStringsSep " " lib.escapeShellArg agentCommand;

      agentStartScript =
        if agentCommand == [ ] then
          "${pkgs.coreutils}/bin/sleep infinity"
        else
          "${pkgs.writeShellScript "agent-sandcastle-agent-command" ''
            set -eu
            exec /run/current-system/sw/bin/sandbox-happy-session ${agentCommandLine}
          ''}";
    in
    {
      imports = [ ./base-image.nix ];

      assertions = [
        {
          assertion = validName name;
          message = "agent-sandcastle sandbox names must start with an alphanumeric character and contain only letters, numbers, '.', '_' or '-'.";
        }
      ];

      networking.hostName = lib.mkDefault name;

      microvm = {
        vcpu = lib.mkDefault vcpu;
        mem = lib.mkDefault memoryMiB;
        socket = lib.mkDefault "${name}.sock";

        volumes = lib.mkDefault [
          {
            image = "${name}-home.img";
            mountPoint = "/home/dev";
            size = diskSizeMiB;
          }
        ];

        interfaces = lib.mkDefault [
          {
            type = "user";
            id = "qemu";
            mac = macForName name;
          }
        ];

        forwardPorts = lib.mkDefault (
          lib.optional (sshHostPort != null) {
            from = "host";
            host.port = sshHostPort;
            guest.port = 22;
          }
        );
      };

      users.users.dev.openssh.authorizedKeys.keys = authorizedKeys;

      environment.etc."agent-sandcastle/session.env".text =
        lib.generators.toKeyValue { } {
          SANDBOX_NAME = name;
          REPO_URL = repoUrlValue;
          BRANCH = branchValue;
          WORKDIR = workdir;
          AGENT_KEY = agentKey;
          AGENT_AUTH_MODE = agentAuthMode;
          HAPPY_RELAY_URL = happyRelayUrl;
          HAPPY_SESSION_NAME = happySessionName;
        } + "\n";

      systemd.services.sandbox-init = {
        description = "Prepare the agent-sandcastle sandbox workspace";
        wantedBy = [ "multi-user.target" ];
        after = [ "network-online.target" ];
        wants = [ "network-online.target" ];
        path = [
          pkgs.coreutils
          pkgs.git
          pkgs.util-linux
        ];
        serviceConfig.Type = "oneshot";
        script = ''
          repo_url=${lib.escapeShellArg repoUrlValue}
          branch=${lib.escapeShellArg branchValue}
          workdir=${lib.escapeShellArg workdir}
          sandbox_name=${lib.escapeShellArg name}

          parent_dir="$(${pkgs.coreutils}/bin/dirname "$workdir")"
          install -d -o dev -g users "$parent_dir" /home/dev/.agent-sandcastle

          if [ -n "$repo_url" ]; then
            if [ ! -d "$workdir/.git" ]; then
              if [ -e "$workdir" ]; then
                echo "$workdir exists but is not a git checkout; refusing to overwrite it" >&2
                exit 1
              fi

              if [ -n "$branch" ]; then
                runuser -u dev -- git clone --branch "$branch" "$repo_url" "$workdir"
              else
                runuser -u dev -- git clone "$repo_url" "$workdir"
              fi
            fi
          else
            install -d -o dev -g users "$workdir"
          fi

          printf '%s\n' "$sandbox_name" > /home/dev/.agent-sandcastle/current-sandbox-id
          chown -R dev:users /home/dev/.agent-sandcastle
        '';
      };

      systemd.services.happy-session = {
        description = "Agent Sandcastle Happy session";
        wantedBy = [ "multi-user.target" ];
        after = [ "sandbox-init.service" ];
        requires = [ "sandbox-init.service" ];
        path = [
          pkgs.bashInteractive
          pkgs.claude-code
          pkgs.codex
          pkgs.coreutils
          pkgs.git
          pkgs.happy-coder
        ];
        serviceConfig = {
          User = "dev";
          Group = "users";
          WorkingDirectory = workdir;
          EnvironmentFile = "/etc/agent-sandcastle/session.env";
          ExecStart = agentStartScript;
          Restart = "on-failure";
        };
      };
    };
}
