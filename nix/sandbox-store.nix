{ config, lib, pkgs, ... }:

let
  cfg = config.services.agent-sandcastle.sandboxStore;
in
{
  options.services.agent-sandcastle.sandboxStore = {
    enable = lib.mkEnableOption "the agent-sandcastle curated sandbox store staging service";

    path = lib.mkOption {
      type = lib.types.path;
      default = "/var/lib/agent-sandcastle/store";
      description = "Host path reserved for the curated sandbox-only store.";
    };

    closureRoots = lib.mkOption {
      type = lib.types.listOf lib.types.package;
      default = [ ];
      description = "Derivations that should become roots of the curated sandbox closure.";
    };
  };

  config = lib.mkIf cfg.enable {
    systemd.tmpfiles.rules = [
      "d /var/lib/agent-sandcastle 0750 root root -"
      "d ${toString cfg.path} 0755 root root -"
    ];

    systemd.services.agent-sandcastle-sandbox-store = {
      description = "Prepare the agent-sandcastle curated sandbox store path";
      wantedBy = [ "multi-user.target" ];
      path = [ pkgs.coreutils ];
      serviceConfig.Type = "oneshot";
      script = ''
        install -d -m 0755 ${lib.escapeShellArg (toString cfg.path)}
        ${lib.concatMapStringsSep "\n" (root: "test -e ${lib.escapeShellArg (toString root)}") cfg.closureRoots}
        printf '%s\n' 'curated sandbox store population will be wired after the base microvm boots.' > ${lib.escapeShellArg (toString cfg.path)}/README
      '';
    };
  };
}

