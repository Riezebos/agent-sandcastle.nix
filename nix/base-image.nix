{ lib, pkgs, ... }:

let
  sandboxHappySession = pkgs.writeShellScriptBin "sandbox-happy-session" ''
    set -eu

    export HOME="''${HOME:-/home/dev}"
    export CODEX_HOME="''${CODEX_HOME:-$HOME/.codex}"
    mkdir -p "$HOME/.happy" "$CODEX_HOME"

    if [ "$#" -eq 0 ]; then
      echo "sandbox-happy-session: no agent command configured; sandbox is idle."
      exec ${pkgs.coreutils}/bin/sleep infinity
    fi

    case "$1" in
      claude|claude-code)
        shift
        if [ -n "''${CLAUDE_CODE_OAUTH_TOKEN:-}" ]; then
          rm -f "$HOME/.claude/.credentials.json"
        fi
        exec ${lib.getExe pkgs.happy-coder} "$@"
        ;;
      codex)
        shift
        exec ${lib.getExe pkgs.happy-coder} codex "$@"
        ;;
      *)
        exec ${lib.getExe pkgs.happy-coder} acp -- "$@"
        ;;
    esac
  '';
in
{
  system.stateVersion = lib.mkDefault lib.trivial.release;

  microvm = {
    guest.enable = lib.mkDefault true;
    optimize.enable = lib.mkDefault true;
    hypervisor = lib.mkDefault "qemu";
    vcpu = lib.mkDefault 2;
    mem = lib.mkDefault 2304;
  };

  networking = {
    useDHCP = lib.mkDefault true;
    firewall.allowedTCPPorts = [ 22 ];
  };

  fileSystems = {
    "/tmp" = {
      device = lib.mkDefault "tmpfs";
      fsType = lib.mkDefault "tmpfs";
      options = lib.mkDefault [
        "mode=1777"
        "nosuid"
        "nodev"
        "size=50%"
      ];
    };

    "/var/tmp" = {
      device = lib.mkDefault "tmpfs";
      fsType = lib.mkDefault "tmpfs";
      options = lib.mkDefault [
        "mode=1777"
        "nosuid"
        "nodev"
        "size=50%"
      ];
    };

    "/home/dev/.cache" = {
      device = lib.mkDefault "tmpfs";
      fsType = lib.mkDefault "tmpfs";
      options = lib.mkDefault [
        "mode=0700"
        "nosuid"
        "nodev"
        "size=25%"
      ];
    };
  };

  systemd.tmpfiles.rules = [
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
      };
    };
  };

  programs.bash.completion.enable = true;

  nix = {
    channel.enable = false;
    settings.experimental-features = [
      "nix-command"
      "flakes"
    ];
  };

  documentation = {
    enable = lib.mkDefault false;
    man.enable = lib.mkDefault false;
    info.enable = lib.mkDefault false;
    doc.enable = lib.mkDefault false;
  };

  environment.systemPackages = with pkgs; [
    bashInteractive
    claude-code
    coreutils
    codex
    curl
    git
    happy-coder
    htop
    jq
    less
    openssh
    ripgrep
    sandboxHappySession
    vim
  ];
}
