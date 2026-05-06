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
      agentOverlay = _final: _prev: {
        inherit (agentPackages) claude-code codex happy-coder;
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

      smokeVm = mkNixos [
        microvm.nixosModules.microvm
        self.nixosModules.base
        (self.lib.mkSandbox {
          name = "sandcastle-smoke";
          sshHostPort = 2222;
        })
      ];

      exampleHost = mkNixos [
        self.nixosModules.host
        ({ config, ... }: {
          networking.hostName = "agent-sandcastle-example";
          system.stateVersion = lib.trivial.release;

          boot.loader.grub.devices = [ "nodev" ];
          fileSystems."/" = {
            device = "tmpfs";
            fsType = "tmpfs";
          };

          services.agent-sandcastle.sandboxStore = {
            enable = true;
            closureRoots = [
              config.microvm.vms.smoke.config.config.system.build.toplevel
              config.microvm.vms.smoke.config.config.microvm.declaredRunner
            ];
          };
          services.agent-sandcastle.networking.enable = true;

          microvm.vms.smoke = {
            autostart = false;
            config = self.lib.mkSandbox {
              name = "smoke";
              networkMode = "tap";
              useCuratedStore = true;
            };
          };
        })
      ];
    in
    {
      lib = import ./nix/sandbox.nix {
        inherit lib;
      };

      nixosModules = {
        default = self.nixosModules.host;

        base = { ... }: {
          imports = [ ./nix/base-image.nix ];
          nixpkgs.overlays = [ agentOverlay ];
        };

        sandboxStore = import ./nix/sandbox-store.nix;
        sandboxNetwork = import ./nix/sandbox-network.nix;

        host = { ... }: {
          imports = [
            microvm.nixosModules.host
            self.nixosModules.sandboxStore
            self.nixosModules.sandboxNetwork
          ];

          nixpkgs.overlays = [
            microvm.overlays.default
            agentOverlay
          ];
        };
      };

      nixosConfigurations = {
        sandbox-smoke = smokeVm;
        example-host = exampleHost;
      };

      packages.${system} = {
        default = self.packages.${system}.sandbox-smoke;

        claude-code = agentPackages.claude-code;
        codex = agentPackages.codex;
        happy-cli = self.packages.${system}.happy-coder;
        happy-coder = agentPackages.happy-coder;

        sandbox-smoke = smokeVm.config.microvm.declaredRunner;

        sandbox-store = pkgs.closureInfo {
          rootPaths = [
            smokeVm.config.system.build.toplevel
          ];
        };
      };

      apps.${system} = {
        default = self.apps.${system}.sandbox-smoke;

        sandbox-smoke = {
          type = "app";
          program = "${self.packages.${system}.sandbox-smoke}/bin/microvm-run";
        };
      };

      checks.${system}.sandbox-smoke-runner = self.packages.${system}.sandbox-smoke;
    };
}
