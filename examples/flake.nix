{
  description = "Minimal downstream sandcastle host";

  inputs = {
    # Replace this with your fork or pinned release.
    # For local verification in this repo, use .#nixosConfigurations.example-cli-host.
    agent-sandcastle.url = "github:OWNER/agent-sandcastle";

    nixpkgs.follows = "agent-sandcastle/nixpkgs";
    microvm.follows = "agent-sandcastle/microvm";
  };

  outputs = { nixpkgs, microvm, agent-sandcastle, ... }:
    let
      system = "x86_64-linux";

      hostBase = { ... }: {
        networking.hostName = "agent-sandcastle-example";
        system.stateVersion = nixpkgs.lib.trivial.release;

        boot.loader.grub.devices = [ "nodev" ];
        fileSystems."/" = {
          device = "tmpfs";
          fsType = "tmpfs";
        };
      };

      # Sandboxes are created at runtime with the `sandcastle` CLI, not
      # declared here. The host module only provides the state directories,
      # the MicroVM state root, address and CID allocation, and the CLI
      # itself; `sandcastle create` then allocates a specification and builds
      # a runner from this flake's pinned inputs.
      sandcastleHost = { ... }: {
        services.sandcastle = {
          enable = true;

          # Zone the per-sandbox Caddy route snippets are emitted under.
          routeZone = "sandboxes.example.com";

          # Cap concurrently running sandboxes on a shared host.
          maxRunning = 4;
        };

        # Bridge, DNS, NAT, and egress filtering for the sandbox network.
        services.agent-sandcastle.networking.enable = true;
      };
    in
    {
      nixosConfigurations.sandcastle-host = nixpkgs.lib.nixosSystem {
        inherit system;
        modules = [
          agent-sandcastle.nixosModules.sandcastleHost
          hostBase
          sandcastleHost
        ];
      };
    };
}
