{ self }:
{ config, lib, pkgs, ... }:

let
  cfg = config.services.agent-sandcastle.launcher;
in
{
  options.services.agent-sandcastle.launcher = {
    enable = lib.mkEnableOption "agent-sandcastle Phoenix LiveView launcher";

    package = lib.mkOption {
      type = lib.types.package;
      default = self.packages.${pkgs.stdenv.hostPlatform.system}.launcher;
      defaultText = lib.literalExpression
        "agent-sandcastle.packages.\${pkgs.system}.launcher";
      description = ''
        The launcher mix release. Override to test a fork without changing the
        flake input pin.
      '';
    };

    user = lib.mkOption {
      type = lib.types.str;
      default = "agent-sandcastle";
      description = "System user that owns the launcher state directory.";
    };

    group = lib.mkOption {
      type = lib.types.str;
      default = "agent-sandcastle";
      description = "Primary group for the launcher user.";
    };

    host = lib.mkOption {
      type = lib.types.str;
      default = "localhost";
      description = ''
        External hostname rendered into LiveView/URL helpers via PHX_HOST.
        Caddy terminates TLS in front of the launcher, so this is what users
        see in the address bar, not what the unit binds to.
      '';
    };

    bindAddress = lib.mkOption {
      type = lib.types.str;
      default = "127.0.0.1";
      description = ''
        Loopback IP the launcher's HTTP listener binds to. Caddy/Authentik
        forward to this address; sandboxes are blocked from reaching it by
        the host nftables rules in `nix/sandbox-network.nix`.
      '';
    };

    port = lib.mkOption {
      type = lib.types.port;
      default = 4000;
      description = "TCP port for the launcher HTTP listener.";
    };

    stateDirectory = lib.mkOption {
      type = lib.types.str;
      default = "agent-sandcastle";
      description = ''
        systemd `StateDirectory=` name. The launcher's SQLite database lives
        underneath `/var/lib/<stateDirectory>/`.
      '';
    };

    databasePath = lib.mkOption {
      type = lib.types.str;
      default = "/var/lib/${cfg.stateDirectory}/state.db";
      defaultText = lib.literalExpression
        "\"/var/lib/\${cfg.stateDirectory}/state.db\"";
      description = "Absolute path to the launcher SQLite database.";
    };

    environmentFile = lib.mkOption {
      type = lib.types.path;
      example = "/run/secrets/agent-sandcastle-launcher.env";
      description = ''
        Path to a systemd `EnvironmentFile` containing at least
        `SECRET_KEY_BASE=` (≥64 bytes, base64) and `RELEASE_COOKIE=`. Provide
        this from sops-nix or another out-of-band secret manager; the launcher
        unit refuses to start if either variable is missing.
      '';
    };

    extraEnvironment = lib.mkOption {
      type = lib.types.attrsOf lib.types.str;
      default = { };
      description = ''
        Additional environment variables passed to the launcher unit. Use
        sparingly — long-lived values belong in `environmentFile`.
      '';
    };
  };

  config = lib.mkIf cfg.enable {
    users.users.${cfg.user} = {
      isSystemUser = true;
      group = cfg.group;
      description = "agent-sandcastle launcher";
      home = "/var/lib/${cfg.stateDirectory}";
    };

    users.groups.${cfg.group} = { };

    systemd.services.agent-sandcastle-launcher = {
      description = "agent-sandcastle Phoenix LiveView launcher";
      wantedBy = [ "multi-user.target" ];
      after = [ "network-online.target" ];
      wants = [ "network-online.target" ];

      environment = {
        PHX_SERVER = "true";
        PHX_HOST = cfg.host;
        PHX_HTTP_IP = cfg.bindAddress;
        PORT = toString cfg.port;
        LAUNCHER_DATABASE_PATH = cfg.databasePath;
        LANG = "C.UTF-8";
        LC_ALL = "C.UTF-8";
      } // cfg.extraEnvironment;

      serviceConfig = {
        Type = "exec";
        User = cfg.user;
        Group = cfg.group;
        StateDirectory = cfg.stateDirectory;
        WorkingDirectory = "/var/lib/${cfg.stateDirectory}";
        EnvironmentFile = cfg.environmentFile;
        ExecStartPre = "${cfg.package}/bin/agent_sandcastle_launcher eval \"AgentSandcastleLauncher.Release.migrate()\"";
        ExecStart = "${cfg.package}/bin/agent_sandcastle_launcher start";
        Restart = "on-failure";
        RestartSec = "5s";

        # Hardening. The launcher's blast radius is the same as the host
        # (it shells out to `microvm`/`qemu-img` and edits /var/lib/microvms),
        # so we can't lock it down to NoNewPrivileges + ProtectSystem=strict
        # without breaking those flows. The settings below cover what the
        # current dry-run scope can tolerate; revisit when M2 wires the host
        # adapter that actually starts/stops microVM units.
        ProtectHome = true;
        PrivateTmp = true;
        ProtectKernelTunables = true;
        ProtectKernelModules = true;
        ProtectKernelLogs = true;
        ProtectControlGroups = true;
        RestrictNamespaces = true;
        RestrictRealtime = true;
        LockPersonality = true;
        MemoryDenyWriteExecute = false; # BEAM JIT requires W+X.
      };
    };
  };
}
