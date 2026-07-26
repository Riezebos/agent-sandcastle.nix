{self}: {
  config,
  lib,
  pkgs,
  ...
}: let
  cfg = config.services.sandcastle;

  jsonFormat = pkgs.formats.json {};

  hostConfig = {
    stateDir = cfg.stateDir;
    gcRootDir = cfg.gcRootDir;
    flakeRef = cfg.flakeRef;
    bridge = cfg.bridge;
    subnet = cfg.subnet;
    hostAddress = cfg.hostAddress;
    allocationStart = cfg.allocationStart;
    allocationEnd = cfg.allocationEnd;
    vsockCidStart = cfg.vsockCidStart;
    vsockCidEnd = cfg.vsockCidEnd;
    routeZone = cfg.routeZone;
    maxRunning = cfg.maxRunning;
    vmUser = "microvm";
    vmGroup = "kvm";
    nameservers = cfg.nameservers;
  };

  # microvm.nix's tap-up script creates the TAP device but leaves it
  # unattached. Runtime-created sandboxes are not in config.microvm.vms, so
  # the host cannot enumerate them at build time; instead every sandcastle
  # TAP device that has no master yet is attached after tap-up. Attaching an
  # already-attached device is a no-op, so concurrent starts converge.
  attachTaps = pkgs.writeShellApplication {
    name = "sandcastle-attach-taps";
    runtimeInputs = [pkgs.iproute2];
    text = ''
      bridge=${lib.escapeShellArg cfg.bridge}

      for path in /sys/class/net/${cfg.tapPrefix}*; do
        [ -e "$path" ] || continue
        device="$(basename "$path")"
        [ -e "$path/master" ] && continue
        ip link set dev "$device" master "$bridge"
        ip link set dev "$device" up
      done
    '';
  };
in {
  options.services.sandcastle = {
    enable = lib.mkEnableOption ''
      the sandcastle CLI host: state directories, MicroVM state root, and the
      `sandcastle` command used over SSH to manage development sandboxes
    '';

    package = lib.mkOption {
      type = lib.types.package;
      default = self.packages.${pkgs.stdenv.hostPlatform.system}.sandcastle;
      defaultText = lib.literalExpression "agent-sandcastle.packages.\${pkgs.system}.sandcastle";
      description = "The sandcastle CLI package installed on this host.";
    };

    flakeRef = lib.mkOption {
      type = lib.types.str;
      default = "${self}";
      defaultText = lib.literalExpression "\"\${agent-sandcastle}\"";
      description = ''
        Flake reference sandbox runners are built from. Defaults to the store
        path of the agent-sandcastle flake this host was built with, so a
        sandbox rebuild uses the same pinned nixpkgs and microvm.nix as the
        host, without any network access.
      '';
    };

    stateDir = lib.mkOption {
      type = lib.types.str;
      default = "/var/lib/sandcastle";
      description = ''
        Root of every piece of mutable sandbox state: specifications, VM
        directories and disks, credentials, locks, known-hosts, and Caddy
        route snippets.
      '';
    };

    gcRootDir = lib.mkOption {
      type = lib.types.str;
      default = "/nix/var/nix/gcroots/sandcastle";
      description = ''
        Directory holding one GC root per installed sandbox runner, so
        `nix-collect-garbage` cannot remove a runner a sandbox is using or
        the previous runner a rollback needs.
      '';
    };

    bridge = lib.mkOption {
      type = lib.types.str;
      default = "br-sandboxes";
      description = ''
        Host bridge sandbox TAP devices are attached to. Enable a sandbox
        network module that actually creates this bridge, provides DNS, and
        filters egress.
      '';
    };

    tapPrefix = lib.mkOption {
      type = lib.types.str;
      default = "sc-";
      description = ''
        Prefix of the TAP device names sandcastle guests declare. Must match
        `tapPrefix` in nix/guest-module.nix.
      '';
    };

    subnet = lib.mkOption {
      type = lib.types.str;
      default = "10.88.0.0/24";
      description = "IPv4 subnet routed behind the sandbox bridge.";
    };

    hostAddress = lib.mkOption {
      type = lib.types.str;
      default = "10.88.0.1";
      description = "Bridge address on the host. Sandboxes use it as gateway and resolver.";
    };

    allocationStart = lib.mkOption {
      type = lib.types.str;
      default = "10.88.0.16";
      description = "First IPv4 address the CLI may allocate to a sandbox.";
    };

    allocationEnd = lib.mkOption {
      type = lib.types.str;
      default = "10.88.0.239";
      description = "Last IPv4 address the CLI may allocate to a sandbox.";
    };

    vsockCidStart = lib.mkOption {
      type = lib.types.ints.positive;
      default = 100;
      description = "First VSOCK context ID the CLI may allocate.";
    };

    vsockCidEnd = lib.mkOption {
      type = lib.types.ints.positive;
      default = 65535;
      description = "Last VSOCK context ID the CLI may allocate.";
    };

    routeZone = lib.mkOption {
      type = lib.types.str;
      default = "example.com";
      description = "DNS zone sandbox web routes must be a subdomain of.";
    };

    maxRunning = lib.mkOption {
      type = lib.types.ints.positive;
      default = 4;
      description = ''
        Maximum number of sandboxes allowed to run at once on this shared
        host. Enforced by the CLI before it starts another VM.
      '';
    };

    nameservers = lib.mkOption {
      type = lib.types.listOf lib.types.str;
      default = [cfg.hostAddress];
      defaultText = lib.literalExpression "[ config.services.sandcastle.hostAddress ]";
      description = "Resolvers configured inside sandbox guests.";
    };
  };

  config = lib.mkIf cfg.enable {
    assertions = [
      {
        assertion = cfg.flakeRef != "";
        message = ''
          services.sandcastle.flakeRef must not be empty; the CLI has no
          other way to evaluate a sandbox runner.
        '';
      }
      {
        assertion = lib.hasPrefix "/" cfg.stateDir && lib.hasPrefix "/" cfg.gcRootDir;
        message = "services.sandcastle.stateDir and gcRootDir must be absolute paths.";
      }
    ];

    # Runtime-created sandboxes live where the CLI can find them, next to
    # their specs and disks, rather than under microvm.nix's default root.
    microvm.stateDir = "${cfg.stateDir}/vms";

    environment.systemPackages = [cfg.package];

    environment.etc."sandcastle/config.json".source =
      jsonFormat.generate "sandcastle-config.json" hostConfig;

    # The state root is traversable so the unprivileged microvm user can
    # reach its own VM directories, but only root may list or read the
    # specs, credentials, locks, and known-hosts trees.
    systemd.tmpfiles.settings."10-sandcastle" = {
      "${cfg.stateDir}".d = {
        user = "root";
        group = "root";
        mode = "0751";
      };
      "${cfg.stateDir}/specs".d = {
        user = "root";
        group = "root";
        mode = "0700";
      };
      "${cfg.stateDir}/credentials".d = {
        user = "root";
        group = "root";
        mode = "0700";
      };
      "${cfg.stateDir}/locks".d = {
        user = "root";
        group = "root";
        mode = "0700";
      };
      "${cfg.stateDir}/known-hosts".d = {
        user = "root";
        group = "root";
        mode = "0700";
      };
      "${cfg.stateDir}/caddy".d = {
        user = "root";
        group = "root";
        mode = "0755";
      };
      "${cfg.gcRootDir}".d = {
        user = "root";
        group = "root";
        mode = "0755";
      };
    };

    systemd.services."microvm-tap-interfaces@".serviceConfig.ExecStartPost = [
      (lib.getExe attachTaps)
    ];
  };
}
