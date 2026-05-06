{ config, lib, pkgs, ... }:

let
  cfg = config.services.agent-sandcastle.sandboxStore;

  closureInfo = pkgs.closureInfo {
    rootPaths = cfg.closureRoots;
  };

  # Must match nix/sandbox.nix's curatedStoreTag.
  curatedStoreTag = "agent-sandcastle-curated-store";

  guestConfigOf = vm:
    if vm.config != null then vm.config.config
    else if vm.evaluatedConfig != null then vm.evaluatedConfig.config
    else null;

  vmUsesCuratedStore = vm:
    let g = guestConfigOf vm;
    in g != null
      && builtins.any (s: s.tag == curatedStoreTag) g.microvm.shares;
in
{
  options.services.agent-sandcastle.sandboxStore = {
    enable = lib.mkEnableOption ''
      the agent-sandcastle curated sandbox store. The host realises a
      chroot Nix store holding the union closure of every sandbox's
      runtime, so sandbox VMs can virtiofs-mount that curated subset as
      /nix/.ro-store and let microvm.nix bind or overlay it into
      /nix/store - never the host's main /nix/store
    '';

    path = lib.mkOption {
      type = lib.types.path;
      default = "/var/lib/agent-sandcastle/store";
      description = ''
        Host directory holding the curated chroot store. Populated as a
        chroot Nix store, so the actual store paths live at
        ''${path}/nix/store - which is the path virtiofsd serves through
        the guest's read-only store share.
      '';
    };

    closureRoots = lib.mkOption {
      type = lib.types.listOf lib.types.package;
      default = [ ];
      example = lib.literalExpression ''
        [
          config.microvm.vms.smoke.config.config.system.build.toplevel
          pkgs.claude-code
          pkgs.codex
          pkgs.happy-coder
        ]
      '';
      description = ''
        Derivations whose union closure is realised into the curated
        store. Should include the sandbox base image toplevel and every
        agent CLI a sandbox is allowed to invoke.
      '';
    };
  };

  config = lib.mkIf cfg.enable {
    assertions = [
      {
        assertion = cfg.closureRoots != [ ];
        message = ''
          services.agent-sandcastle.sandboxStore.closureRoots must contain
          at least one root (typically a sandbox base image toplevel and
          any agent CLI packages exposed to sandboxes); otherwise the
          curated store would be empty and sandboxes could not boot.
        '';
      }
    ];

    systemd.tmpfiles.rules = [
      "d /var/lib/agent-sandcastle 0750 root root -"
      "d ${toString cfg.path} 0755 root root -"
    ];

    systemd.services = lib.mkMerge ([
      {
        agent-sandcastle-sandbox-store = {
          description = "Populate the agent-sandcastle curated sandbox store";
          wantedBy = [ "multi-user.target" ];
          before = [ "microvms.target" ];
          after = [ "local-fs.target" ];

          path = [ pkgs.nix pkgs.coreutils pkgs.findutils ];

          serviceConfig = {
            Type = "oneshot";
            RemainAfterExit = true;
          };

          script = ''
            set -eu

            root=${lib.escapeShellArg (toString cfg.path)}
            install -d -m 0755 "$root"

            xargs --arg-file=${closureInfo}/store-paths -- \
              nix --extra-experimental-features 'nix-command' \
                copy --no-check-sigs --to "local?root=$root"
          '';
        };
      }
    ] ++ (lib.mapAttrsToList (vmName: vm:
      lib.mkIf (vmUsesCuratedStore vm) {
        # Run virtiofsd for this VM in a private mount namespace where
        # /nix/store is bind-mounted from the curated chroot store. The
        # virtiofsd `--shared-dir=/nix/store` argument (set by the
        # microvm.shares entry's source in mkSandbox) then serves the
        # curated subset to the guest's /nix/.ro-store, while the host's
        # actual /nix/store stays invisible to virtiofsd and to the guest.
        "microvm-virtiofsd@${vmName}" = {
          after = [ "agent-sandcastle-sandbox-store.service" ];
          requires = [ "agent-sandcastle-sandbox-store.service" ];
          serviceConfig = {
            PrivateMounts = true;
            BindReadOnlyPaths = [
              "${toString cfg.path}/nix/store:/nix/store"
            ];
          };
        };
      }
    ) config.microvm.vms));
  };
}
