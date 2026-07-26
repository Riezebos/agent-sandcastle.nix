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
      elixir = pkgs.beamMinimalPackages.elixir;
      agentPackages = llm-agents.packages.${system};

      launcher = pkgs.callPackage ./nix/launcher.nix {
        # Re-derive after editing `launcher/mix.lock`:
        #   nix build "path:$PWD#launcher" — copy the `got:` hash, paste here.
        fetchMixDepsHash = "sha256-Hjluglh8h1zDt1UCOARgXiasEAIDUNr7nxX94QxsZ2U=";
      };

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
      };
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

      exampleHostBase = { ... }: {
        networking.hostName = "agent-sandcastle-example";
        system.stateVersion = lib.trivial.release;

        boot.loader.grub.devices = [ "nodev" ];
        fileSystems."/" = {
          device = "tmpfs";
          fsType = "tmpfs";
        };
      };

      exampleHost = mkNixos [
        self.nixosModules.host
        exampleHostBase
        ({ config, ... }: {
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

      exampleAgentHost = mkNixos [
        self.nixosModules.host
        exampleHostBase
        (import ./examples/agent-sandboxes.nix {
          agent-sandcastle = self;
        })
      ];

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

      exampleLauncherHost = mkNixos [
        self.nixosModules.host
        self.nixosModules.launcher
        exampleHostBase
        ({ ... }: {
          # The actual file is provisioned out-of-band (sops-nix, deploy SSH,
          # etc.). For eval/build coverage we only need the path to exist as a
          # placeholder; runtime tests stage a real file.
          services.agent-sandcastle.launcher = {
            enable = true;
            host = "sandboxes.example.com";
            environmentFile = "/var/lib/agent-sandcastle/example-launcher.env";
          };
        })
      ];
    in
    {
      # `mkSandbox` belongs to the retired declarative path and is removed in
      # M6; `runnerFromSpecFile` and friends are the CLI-first entry points.
      lib =
        (import ./nix/sandbox.nix {
          inherit lib;
        })
        // sandboxBuilder;

      nixosModules = {
        default = self.nixosModules.host;

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

        base = { ... }: {
          imports = [ ./nix/base-image.nix ];
          nixpkgs.overlays = [ agentOverlay ];
        };

        sandboxStore = import ./nix/sandbox-store.nix;
        sandboxNetwork = import ./nix/sandbox-network.nix;
        launcher = import ./nix/launcher-module.nix { inherit self; };

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
        example-agent-host = exampleAgentHost;
        example-cli-host = exampleCliHost;
        example-launcher-host = exampleLauncherHost;
      };

      packages.${system} = {
        default = self.packages.${system}.sandcastle;

        claude-code = agentPackages.claude-code;
        codex = agentPackages.codex;
        happy-cli = self.packages.${system}.happy-coder;
        happy-coder = agentPackages.happy-coder;

        launcher = launcher;

        inherit sandcastle;

        # A runner built the way `sandcastle build` builds one, for eval and
        # build coverage without a running host.
        sandbox-example-runner = sandboxBuilder.runnerFromSpec exampleSandboxSpec;

        sandbox-smoke = smokeVm.config.microvm.declaredRunner;

        sandbox-store = pkgs.closureInfo {
          rootPaths = [
            smokeVm.config.system.build.toplevel
          ];
        };
      };

      apps.${system} = {
        default = self.apps.${system}.sandcastle;

        sandcastle = {
          type = "app";
          program = "${sandcastle}/bin/sandcastle";
        };

        sandbox-smoke = {
          type = "app";
          program = "${self.packages.${system}.sandbox-smoke}/bin/microvm-run";
        };
      };

      checks.${system} = {
        # Builds the CLI and runs its unit tests as part of the derivation.
        sandcastle = sandcastle;
        sandbox-example-runner = self.packages.${system}.sandbox-example-runner;
        example-cli-host-toplevel = exampleCliHost.config.system.build.toplevel;

        sandbox-smoke-runner = self.packages.${system}.sandbox-smoke;
        example-host-toplevel = exampleHost.config.system.build.toplevel;
        example-agent-host-toplevel = exampleAgentHost.config.system.build.toplevel;
        example-launcher-host-toplevel = exampleLauncherHost.config.system.build.toplevel;
        launcher-release = launcher;
        launcher-syntax = pkgs.runCommand "agent-sandcastle-launcher-syntax"
          {
            nativeBuildInputs = [ elixir ];
            src = ./launcher;
          }
          ''
            cp -R "$src" launcher
            cd launcher
            elixir -e 'Path.wildcard("{config,lib,test}/**/*.{ex,exs}") |> Enum.each(fn file -> Code.string_to_quoted!(File.read!(file), file: file) end)'
            touch "$out"
          '';
      };

      devShells.${system}.launcher = pkgs.mkShell {
        packages = [
          pkgs.chromium
          elixir
          pkgs.gnumake
          pkgs.inotify-tools
          pkgs.pkg-config
          pkgs.sqlite
          pkgs.stdenv.cc
        ];

        shellHook = ''
          export MIX_HOME="$PWD/.mix"
          export HEX_HOME="$PWD/.hex"
          export XDG_CACHE_HOME="$PWD/.cache"
          export ELIXIR_MAKE_CACHE="$XDG_CACHE_HOME/elixir_make"
          export RODNEY_HOME="$PWD/.rodney"
          export PATH="$MIX_HOME/bin:$PATH"
        '';
      };
    };
}
