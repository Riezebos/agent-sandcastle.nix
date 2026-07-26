{
  config,
  lib,
  pkgs,
  ...
}: let
  cfg = config.sandcastle.guest;

  # Kernel interface names are limited to 15 characters, so the TAP device is
  # named from a hash rather than the sandbox name. The host module attaches
  # every device with this prefix to the sandbox bridge, and the CLI derives
  # the same name for diagnostics.
  tapPrefix = "sc-";
  tapName = name: "${tapPrefix}${builtins.substring 0 11 (builtins.hashString "sha256" name)}";

  baseTools = with pkgs; [
    bashInteractive
    bind.dnsutils
    cacert
    coreutils
    curl
    diffutils
    fd
    file
    findutils
    gawk
    git
    gnugrep
    gnused
    gnutar
    gzip
    htop
    iproute2
    iputils
    jq
    less
    openssh
    procps
    ripgrep
    tmux
    unzip
    vim
    which
  ];
in {
  options.sandcastle.guest = {
    enable = lib.mkEnableOption ''
      the sandcastle development guest: an unprivileged `dev` user, SSH over
      VSOCK, a persistent /home/dev volume, and an immutable package set
      built from the sandbox specification
    '';

    name = lib.mkOption {
      type = lib.types.str;
      description = "Sandbox name. Becomes the guest hostname and TAP device hash input.";
    };

    vcpu = lib.mkOption {
      type = lib.types.ints.positive;
      default = 2;
      description = "Virtual CPUs assigned to this sandbox.";
    };

    memoryMiB = lib.mkOption {
      type = lib.types.ints.positive;
      default = 2304;
      description = "Guest RAM in MiB.";
    };

    homeDiskMiB = lib.mkOption {
      type = lib.types.ints.positive;
      default = 16384;
      description = ''
        Size of the persistent raw /home/dev volume in MiB. The image lives
        at `<stateDir>/<name>/home.img` and is the only sandbox state a fork
        copies.
      '';
    };

    mac = lib.mkOption {
      type = lib.types.str;
      description = "Locally administered MAC address allocated by the CLI.";
    };

    vsockCid = lib.mkOption {
      type = lib.types.ints.positive;
      description = "VSOCK context ID used for host-to-guest SSH.";
    };

    machineId = lib.mkOption {
      type = lib.types.strMatching "[0-9a-f]{32}";
      description = ''
        Stable systemd machine identity. Applied through the kernel command
        line so /etc stays fully generated from the immutable system closure.
      '';
    };

    ipv4 = {
      address = lib.mkOption {
        type = lib.types.str;
        description = "Static IPv4 address on the sandbox bridge.";
      };

      prefixLength = lib.mkOption {
        type = lib.types.ints.between 1 32;
        default = 24;
        description = "Prefix length of the sandbox bridge subnet.";
      };

      gateway = lib.mkOption {
        type = lib.types.str;
        description = "Sandbox bridge address on the host. Also the guest's resolver.";
      };
    };

    nameservers = lib.mkOption {
      type = lib.types.listOf lib.types.str;
      default = [];
      description = "Resolvers for the guest. Defaults to the bridge gateway.";
    };

    packageAttrs = lib.mkOption {
      type = lib.types.listOf lib.types.str;
      default = [];
      description = ''
        The nixpkgs attribute paths recorded in the sandbox specification.
        Kept for introspection; `extraPackages` holds what is installed.
      '';
    };

    extraPackages = lib.mkOption {
      type = lib.types.listOf lib.types.package;
      default = [];
      description = "Packages resolved from `packageAttrs` by the sandbox builder.";
    };

    agentPackages = lib.mkOption {
      type = lib.types.listOf lib.types.package;
      default = [];
      description = "Optional coding-agent CLIs such as Claude Code and Codex.";
    };

    authorizedKeys = lib.mkOption {
      type = lib.types.listOf lib.types.str;
      default = [];
      description = ''
        Extra keys accepted for the `dev` user. Host-to-guest SSH runs over
        VSOCK and does not need one, so this is normally empty.
      '';
    };
  };

  config = lib.mkIf cfg.enable {
    system.stateVersion = lib.mkDefault lib.trivial.release;

    networking.hostName = lib.mkDefault cfg.name;

    boot.kernelParams = ["systemd.machine_id=${cfg.machineId}"];

    microvm = {
      guest.enable = lib.mkDefault true;
      optimize.enable = lib.mkDefault true;
      hypervisor = lib.mkDefault "qemu";
      vcpu = cfg.vcpu;
      mem = cfg.memoryMiB;

      # No share with source "/nix/store" is declared, so microvm.nix builds
      # this sandbox its own read-only store image. That is what makes
      # runtime-created sandboxes possible without the host knowing every
      # guest closure root up front.
      shares = lib.mkDefault [];

      volumes = lib.mkDefault [
        {
          image = "home.img";
          mountPoint = "/home/dev";
          size = cfg.homeDiskMiB;
          fsType = "ext4";
          label = "sc-home";
        }
      ];

      interfaces = lib.mkDefault [
        {
          type = "tap";
          id = tapName cfg.name;
          mac = cfg.mac;
          tap.vhost = true;
        }
      ];

      vsock = {
        cid = cfg.vsockCid;
        ssh.enable = true;
      };
    };

    # Static addressing keeps Caddy routes stable and removes lease discovery
    # from every lifecycle operation.
    networking.useDHCP = false;
    networking.useNetworkd = true;
    networking.nameservers =
      if cfg.nameservers == []
      then [cfg.ipv4.gateway]
      else cfg.nameservers;

    systemd.network.networks."10-sandcastle" = {
      matchConfig.MACAddress = cfg.mac;
      address = ["${cfg.ipv4.address}/${toString cfg.ipv4.prefixLength}"];
      routes = [
        {
          Destination = "0.0.0.0/0";
          Gateway = cfg.ipv4.gateway;
          GatewayOnLink = true;
        }
      ];
      networkConfig.IPv6AcceptRA = false;
      linkConfig.RequiredForOnline = "routable";
    };

    networking.nftables.enable = true;
    networking.firewall = {
      enable = true;
      allowedTCPPorts = [];
      # Development servers are reached by the host's Caddy over the bridge.
      # Nothing else can route to a sandbox: the host rejects sandbox-to-
      # sandbox traffic and does not expose the bridge publicly.
      extraInputRules = ''
        ip saddr ${cfg.ipv4.gateway} accept
      '';
    };

    fileSystems = {
      "/tmp" = {
        device = lib.mkDefault "tmpfs";
        fsType = lib.mkDefault "tmpfs";
        options = lib.mkDefault ["mode=1777" "nosuid" "nodev" "size=50%"];
      };

      "/var/tmp" = {
        device = lib.mkDefault "tmpfs";
        fsType = lib.mkDefault "tmpfs";
        options = lib.mkDefault ["mode=1777" "nosuid" "nodev" "size=50%"];
      };

      "/home/dev/.cache" = {
        device = lib.mkDefault "tmpfs";
        fsType = lib.mkDefault "tmpfs";
        options = lib.mkDefault ["mode=0700" "nosuid" "nodev" "size=25%"];
      };
    };

    systemd.tmpfiles.rules = [
      "d /home/dev 0700 dev users -"
      "d /home/dev/.cache 0700 dev users -"
    ];

    services.openssh = {
      enable = true;
      settings = {
        PasswordAuthentication = false;
        KbdInteractiveAuthentication = false;
        PermitRootLogin = "no";
      };
    };

    services.getty.autologinUser = lib.mkDefault "dev";

    security.sudo.enable = false;

    users = {
      mutableUsers = false;
      allowNoPasswordLogin = true;

      users = {
        root.hashedPassword = "!";

        dev = {
          isNormalUser = true;
          description = "Sandbox developer";
          home = "/home/dev";
          createHome = true;
          group = "users";
          openssh.authorizedKeys.keys = cfg.authorizedKeys;
        };
      };
    };

    programs.bash.completion.enable = true;

    nix = {
      channel.enable = false;
      settings.experimental-features = ["nix-command" "flakes"];
    };

    documentation = {
      enable = lib.mkDefault false;
      man.enable = lib.mkDefault false;
      info.enable = lib.mkDefault false;
      doc.enable = lib.mkDefault false;
    };

    # The non-secret half of the sandbox specification, so `sandcastle ssh`
    # sessions can see what the immutable system was built from.
    environment.etc."sandcastle/sandbox.json".text =
      builtins.toJSON {
        name = cfg.name;
        packages = cfg.packageAttrs;
        ipv4 = cfg.ipv4.address;
        vsockCid = cfg.vsockCid;
      }
      + "\n";

    environment.systemPackages = baseTools ++ cfg.agentPackages ++ cfg.extraPackages;
  };
}
