{
  description = "Self-hosted isolated coding-agent sandboxes on NixOS microvms";

  nixConfig = {
    extra-substituters = [ "https://microvm.cachix.org" ];
    extra-trusted-public-keys = [
      "microvm.cachix.org-1:oXnBc6hRE3eX5rSYdRyMYXnfzcCxC7yKPTbZXALsqys="
    ];
  };

  inputs = {
    nixpkgs.url = "github:NixOS/nixpkgs/nixos-unstable";

    microvm = {
      url = "github:microvm-nix/microvm.nix";
      inputs.nixpkgs.follows = "nixpkgs";
    };

    llm-agents = {
      url = "github:numtide/llm-agents.nix";
      inputs.nixpkgs.follows = "nixpkgs";
    };
  };

  outputs = inputs@{ self, nixpkgs, microvm, llm-agents }:
    let
      inherit (nixpkgs) lib;

      system = "x86_64-linux";
      pkgs = nixpkgs.legacyPackages.${system};
      agentPackages = llm-agents.packages.${system};

      sandcastle = pkgs.callPackage ./nix/sandcastle-package.nix { };

      # Turns a validated JSON sandbox specification into a MicroVM runner.
      # `sandcastle build` evaluates `lib.runnerFromSpecFile` against this
      # flake's store path, so a sandbox is always built from the same pinned
      # inputs as the host it runs on.
      sandboxBuilder = import ./nix/sandbox-builder.nix {
        inherit nixpkgs microvm llm-agents system;
      };

      exampleSandboxSpec = {
        schemaVersion = 1;
        name = "cli-example";
        vcpu = 2;
        memoryMiB = 2304;
        homeDiskMiB = 16384;
        packages = [ "nodejs" "uv" ];
        agents = [ "claude-code" "codex" ];
        ipv4 = "10.88.0.16";
        mac = "02:00:aa:bb:cc:dd";
        vsockCid = 100;
        machineId = "0123456789abcdef0123456789abcdef";
        network = {
          gateway = "10.88.0.1";
          prefixLength = 24;
          nameservers = [ "10.88.0.1" ];
        };
        # The CLI substitutes the host's real control key here. A throwaway one
        # keeps the eval-coverage runner shaped like a real one.
        authorizedKeys = [
          "ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIL8sHqFV9M5DBB6r1x8Q0aLmQ9NcbW7dEXAMPLEONLY example"
        ];
      };

      agentOverlay = _final: _prev: {
        inherit (agentPackages) claude-code codex;
      };

      mkNixos = modules:
        lib.nixosSystem {
          inherit system;
          modules = [
            ({ ... }: {
              nixpkgs.overlays = [
                microvm.overlays.default
                agentOverlay
              ];
            })
          ] ++ modules;
        };

      exampleHostBase = { ... }: {
        networking.hostName = "agent-sandcastle-example";
        system.stateVersion = lib.trivial.release;

        boot.loader.grub.devices = [ "nodev" ];
        fileSystems."/" = {
          device = "tmpfs";
          fsType = "tmpfs";
        };
      };

      exampleCliHost = mkNixos [
        self.nixosModules.sandcastleHost
        exampleHostBase
        ({ ... }: {
          services.sandcastle = {
            enable = true;
            routeZone = "sandboxes.example.com";
          };

          # Until M3 replaces it, the CLI host reuses the existing bridge,
          # DNS, and NAT module for the sandbox network.
          services.agent-sandcastle.networking.enable = true;
        })
      ];
    in
    {
      # `runnerFromSpecFile` and friends are the CLI-first entry points: the
      # host evaluates them against a specification the CLI has validated.
      lib = sandboxBuilder;

      nixosModules = {
        default = self.nixosModules.sandcastleHost;

        sandcastleGuest = ./nix/guest-module.nix;

        sandcastleHost = { ... }: {
          imports = [
            microvm.nixosModules.host
            (import ./nix/host-module.nix { inherit self; })
            self.nixosModules.sandboxNetwork
          ];

          nixpkgs.overlays = [
            microvm.overlays.default
            agentOverlay
          ];
        };

        # Exported as a path, not as `import <path>`. NixOS deduplicates
        # imported modules by key, and a path is its own key while a bare
        # function value is not, so a host that pulls this in both directly
        # and through `sandcastleHost` still evaluates.
        sandboxNetwork = ./nix/sandbox-network.nix;
      };

      nixosConfigurations = {
        example-cli-host = exampleCliHost;
      };

      packages.${system} = {
        default = self.packages.${system}.sandcastle;

        claude-code = agentPackages.claude-code;
        codex = agentPackages.codex;

        inherit sandcastle;

        # A runner built the way `sandcastle build` builds one, for eval and
        # build coverage without a running host.
        sandbox-example-runner = sandboxBuilder.runnerFromSpec exampleSandboxSpec;
      };

      apps.${system} = {
        default = self.apps.${system}.sandcastle;

        sandcastle = {
          type = "app";
          program = "${sandcastle}/bin/sandcastle";
        };
      };

      checks.${system} = {
        # Builds the CLI and runs its unit tests as part of the derivation.
        sandcastle = sandcastle;
        sandbox-example-runner = self.packages.${system}.sandbox-example-runner;
        example-cli-host-toplevel = exampleCliHost.config.system.build.toplevel;
      };
    };
}
