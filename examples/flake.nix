{
  description = "Minimal downstream agent-sandcastle host";

  inputs = {
    # Replace this with your fork or pinned release.
    # For local verification in this repo, use .#nixosConfigurations.example-host.
    agent-sandcastle.url = "github:OWNER/agent-sandcastle";

    nixpkgs.follows = "agent-sandcastle/nixpkgs";
    microvm.follows = "agent-sandcastle/microvm";
  };

  outputs = { nixpkgs, microvm, agent-sandcastle, ... }:
    let
      system = "x86_64-linux";
    in
    {
      nixosConfigurations.stub-host = nixpkgs.lib.nixosSystem {
        inherit system;
        modules = [
          agent-sandcastle.nixosModules.host
          ({ config, ... }: {
            networking.hostName = "agent-sandcastle-example";
            system.stateVersion = nixpkgs.lib.trivial.release;

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

            microvm.vms.smoke = {
              autostart = false;
              config = agent-sandcastle.lib.mkSandbox {
                name = "smoke";
                sshHostPort = 2222;
                useCuratedStore = true;
              };
            };
          })
        ];
      };
    };
}
