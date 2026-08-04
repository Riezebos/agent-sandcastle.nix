{
  config,
  lib,
  pkgs,
  ...
}: let
  cfg = config.services.agent-sandcastle.networking;

  ip = "${pkgs.iproute2}/bin/ip";

  guestConfigOf = vm:
    if vm.config != null
    then vm.config.config
    else if vm.evaluatedConfig != null
    then vm.evaluatedConfig.config
    else null;

  sandboxTapIds = vm: let
    guestConfig = guestConfigOf vm;
  in
    if guestConfig == null
    then []
    else
      map (interface: interface.id) (
        builtins.filter
        (interface:
          interface.type
          == "tap"
          && lib.hasPrefix cfg.tapPrefix interface.id)
        guestConfig.microvm.interfaces
      );

  cidrElements = cidrs:
    lib.optionalString (cidrs != []) ''
      elements = { ${lib.concatStringsSep ", " cidrs} }
    '';

  resolveHost = host: ''
    getent ahostsv4 ${lib.escapeShellArg host} \
      | awk '{ print $1 }' \
      | sort -u \
      | while read -r address; do
        [ -n "$address" ] || continue
        nft add element inet agent_sandcastle_egress allowed_dynamic_ipv4 "{ $address }" 2>/dev/null || true
      done

    getent ahostsv6 ${lib.escapeShellArg host} \
      | awk '{ print $1 }' \
      | sort -u \
      | while read -r address; do
        [ -n "$address" ] || continue
        nft add element inet agent_sandcastle_egress allowed_dynamic_ipv6 "{ $address }" 2>/dev/null || true
      done
  '';
in {
  options.services.agent-sandcastle.networking = {
    enable = lib.mkEnableOption ''
      host bridge, DHCP, NAT, and nftables egress filtering for
      agent-sandcastle TAP-backed sandbox VMs
    '';

    bridgeName = lib.mkOption {
      type = lib.types.str;
      default = "br-sandboxes";
      description = "Host bridge that TAP-backed sandboxes attach to.";
    };

    tapPrefix = lib.mkOption {
      type = lib.types.str;
      default = "tap-";
      description = "Prefix for sandbox TAP interfaces managed by this bridge.";
    };

    ipv4 = {
      hostAddress = lib.mkOption {
        type = lib.types.str;
        default = "10.88.0.1";
        description = "IPv4 address of the sandbox bridge without CIDR suffix.";
      };

      prefixLength = lib.mkOption {
        type = lib.types.int;
        default = 24;
        description = "IPv4 prefix length assigned to the sandbox bridge.";
      };

      subnet = lib.mkOption {
        type = lib.types.str;
        default = "10.88.0.0/24";
        description = "IPv4 subnet routed behind the sandbox bridge.";
      };

      dhcpRangeStart = lib.mkOption {
        type = lib.types.str;
        default = "10.88.0.100";
        description = "First IPv4 address dnsmasq may lease to sandboxes.";
      };

      dhcpRangeEnd = lib.mkOption {
        type = lib.types.str;
        default = "10.88.0.254";
        description = "Last IPv4 address dnsmasq may lease to sandboxes.";
      };

      dhcpLeaseTime = lib.mkOption {
        type = lib.types.str;
        default = "12h";
        description = "dnsmasq lease time for sandbox IPv4 addresses.";
      };
    };

    allowedHostnames = lib.mkOption {
      type = lib.types.listOf lib.types.str;
      default = [
        "api.anthropic.com"
        "claude.ai"
        "api.openai.com"
        "auth.openai.com"
        "chatgpt.com"
        "cdn.oaistatic.com"
        "gitlab.com"
        "registry.npmjs.org"
        "pypi.org"
        "files.pythonhosted.org"
        "crates.io"
        "index.crates.io"
        "static.crates.io"
        "proxy.golang.org"
        "sum.golang.org"
      ];
      description = ''
        Hostnames periodically resolved by the host into dynamic nftables
        allowlist sets. This is intentionally exact-hostname based; add
        deployment-specific GitLab and registry hosts here.
        Current enforcement is destination-IP filtering from resolved
        A/AAAA records only: no wildcard domains, DNS-name matching, TLS
        SNI inspection, or HTTP Host-header enforcement happens yet.
      '';
    };

    allowedIPv4Cidrs = lib.mkOption {
      type = lib.types.listOf lib.types.str;
      default = [];
      example = ["203.0.113.10/32"];
      description = "Static IPv4 CIDRs sandboxes may connect to.";
    };

    allowedIPv6Cidrs = lib.mkOption {
      type = lib.types.listOf lib.types.str;
      default = [];
      example = ["2001:db8::10/128"];
      description = "Static IPv6 CIDRs sandboxes may connect to.";
    };
  };

  config = lib.mkIf cfg.enable {
    boot.kernel.sysctl = {
      "net.ipv4.ip_forward" = true;
      "net.ipv6.conf.all.forwarding" = true;
    };

    networking.bridges.${cfg.bridgeName}.interfaces = [];
    networking.interfaces.${cfg.bridgeName} = {
      useDHCP = false;
      ipv4.addresses = [
        {
          address = cfg.ipv4.hostAddress;
          prefixLength = cfg.ipv4.prefixLength;
        }
      ];
    };

    networking.firewall.interfaces.${cfg.bridgeName} = {
      allowedUDPPorts = [
        53
        67
      ];
      allowedTCPPorts = [53];
    };

    services.dnsmasq = {
      enable = true;
      settings = {
        interface = cfg.bridgeName;
        bind-interfaces = true;
        dhcp-authoritative = true;
        dhcp-option = [
          "option:router,${cfg.ipv4.hostAddress}"
          "option:dns-server,${cfg.ipv4.hostAddress}"
        ];
        dhcp-range = [
          "${cfg.ipv4.dhcpRangeStart},${cfg.ipv4.dhcpRangeEnd},${cfg.ipv4.dhcpLeaseTime}"
        ];
        domain-needed = true;
        bogus-priv = true;
        local-service = true;
      };
    };

    # Current allowlisting is IP-set based. The refresh timer resolves exact
    # hostnames into A/AAAA records and nftables filters destination IPs only;
    # runtime validation on a deployed KVM host is still required.
    networking.nftables = {
      enable = true;

      tables = {
        agent_sandcastle_egress = {
          family = "inet";
          content = ''
            set allowed_static_ipv4 {
              type ipv4_addr
              flags interval
              ${cidrElements cfg.allowedIPv4Cidrs}
            }

            set allowed_static_ipv6 {
              type ipv6_addr
              flags interval
              ${cidrElements cfg.allowedIPv6Cidrs}
            }

            set allowed_dynamic_ipv4 {
              type ipv4_addr
              flags interval
            }

            set allowed_dynamic_ipv6 {
              type ipv6_addr
              flags interval
            }

            set blocked_ipv4 {
              type ipv4_addr
              flags interval
              elements = {
                0.0.0.0/8,
                10.0.0.0/8,
                100.64.0.0/10,
                127.0.0.0/8,
                169.254.0.0/16,
                172.16.0.0/12,
                192.168.0.0/16,
                198.18.0.0/15,
                224.0.0.0/4,
                240.0.0.0/4
              }
            }

            set blocked_ipv6 {
              type ipv6_addr
              flags interval
              elements = {
                ::1/128,
                fc00::/7,
                fe80::/10
              }
            }

            chain forward {
              type filter hook forward priority filter; policy accept;

              iifname "${cfg.bridgeName}" oifname "${cfg.bridgeName}" counter reject
              iifname "${cfg.bridgeName}" ip daddr ${cfg.ipv4.hostAddress} udp dport 53 counter accept
              iifname "${cfg.bridgeName}" ip daddr ${cfg.ipv4.hostAddress} tcp dport 53 counter accept
              iifname "${cfg.bridgeName}" ip daddr @allowed_static_ipv4 counter accept
              iifname "${cfg.bridgeName}" ip6 daddr @allowed_static_ipv6 counter accept
              iifname "${cfg.bridgeName}" ip daddr @blocked_ipv4 counter reject
              iifname "${cfg.bridgeName}" ip6 daddr @blocked_ipv6 counter reject
              iifname "${cfg.bridgeName}" ip daddr @allowed_dynamic_ipv4 counter accept
              iifname "${cfg.bridgeName}" ip6 daddr @allowed_dynamic_ipv6 counter accept
              iifname "${cfg.bridgeName}" counter reject
            }
          '';
        };

        agent_sandcastle_nat = {
          family = "ip";
          content = ''
            chain postrouting {
              type nat hook postrouting priority srcnat; policy accept;
              ip saddr ${cfg.ipv4.subnet} oifname != "${cfg.bridgeName}" masquerade
            }
          '';
        };
      };
    };

    systemd.services = lib.mkMerge ([
        {
          dnsmasq = {
            after = [
              "${cfg.bridgeName}-netdev.service"
              "network-addresses-${cfg.bridgeName}.service"
            ];
            requires = [
              "${cfg.bridgeName}-netdev.service"
              "network-addresses-${cfg.bridgeName}.service"
            ];
          };

          agent-sandcastle-egress-allowlist = {
            description = "Refresh agent-sandcastle sandbox egress allowlist";
            after = ["network-online.target" "nftables.service"];
            wants = ["network-online.target"];
            requires = ["nftables.service"];
            path = [
              pkgs.coreutils
              pkgs.gawk
              pkgs.getent
              pkgs.nftables
            ];
            serviceConfig.Type = "oneshot";
            script = ''
              set -eu

              command -v getent >/dev/null

              nft flush set inet agent_sandcastle_egress allowed_dynamic_ipv4
              nft flush set inet agent_sandcastle_egress allowed_dynamic_ipv6

              ${lib.concatMapStringsSep "\n" resolveHost cfg.allowedHostnames}
            '';
          };
        }
      ]
      ++ (lib.mapAttrsToList (
          vmName: vm: let
            tapIds = sandboxTapIds vm;
            attachTaps = pkgs.writeShellScript "agent-sandcastle-attach-${vmName}-taps" ''
              set -eu

              ${lib.concatMapStringsSep "\n" (tapId: ''
                  ${ip} link set dev ${lib.escapeShellArg tapId} master ${lib.escapeShellArg cfg.bridgeName}
                  ${ip} link set dev ${lib.escapeShellArg tapId} up
                '')
                tapIds}
            '';
          in
            lib.mkIf (tapIds != []) {
              "microvm-tap-interfaces@${vmName}" = {
                after = [
                  "${cfg.bridgeName}-netdev.service"
                  "network-addresses-${cfg.bridgeName}.service"
                ];
                requires = [
                  "${cfg.bridgeName}-netdev.service"
                  "network-addresses-${cfg.bridgeName}.service"
                ];
                serviceConfig.ExecStartPost = lib.mkAfter ["+${attachTaps}"];
              };
            }
        )
        config.microvm.vms));

    systemd.timers.agent-sandcastle-egress-allowlist = {
      wantedBy = ["timers.target"];
      timerConfig = {
        OnBootSec = "1min";
        OnUnitActiveSec = "15min";
        Unit = "agent-sandcastle-egress-allowlist.service";
      };
    };
  };
}
