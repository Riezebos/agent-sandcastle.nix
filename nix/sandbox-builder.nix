{
  nixpkgs,
  microvm,
  llm-agents,
  system ? "x86_64-linux",
}: let
  inherit (nixpkgs) lib;

  agentPackages = llm-agents.packages.${system};
  agentOverlay = _final: _prev: {
    inherit (agentPackages) claude-code codex;
  };

  # Mirrors sandcastle/validate.py's PACKAGE_ATTR_RE. The CLI validates first;
  # this is the check that still holds if a specification is hand-edited.
  attrPattern = "[A-Za-z_][A-Za-z0-9_-]*(\\.[A-Za-z_][A-Za-z0-9_-]*){0,3}";

  resolvePackage = pkgs: attr:
    if builtins.match attrPattern attr == null
    then throw "sandcastle: ${attr} is not a valid nixpkgs attribute path"
    else let
      path = lib.splitString "." attr;
    in
      if !lib.hasAttrByPath path pkgs
      then throw "sandcastle: nixpkgs has no attribute ${attr}"
      else let
        value = lib.getAttrFromPath path pkgs;
      in
        if !lib.isDerivation value
        then throw "sandcastle: nixpkgs attribute ${attr} is not a package"
        else value;

  knownAgents = {
    "claude-code" = pkgs: pkgs.claude-code;
    "codex" = pkgs: pkgs.codex;
  };

  resolveAgent = pkgs: name:
    if !(knownAgents ? ${name})
    then throw "sandcastle: unknown agent ${name}"
    else knownAgents.${name} pkgs;

  requireAttr = spec: attr:
    if spec ? ${attr}
    then spec.${attr}
    else throw "sandcastle: sandbox specification is missing '${attr}'";

  systemFromSpec = spec: let
    network = spec.network or {};
  in
    lib.nixosSystem {
      inherit system;
      modules = [
        microvm.nixosModules.microvm
        ./guest-module.nix
        ({pkgs, ...}: {
          nixpkgs.overlays = [
            microvm.overlays.default
            agentOverlay
          ];

          sandcastle.guest = {
            enable = true;
            name = requireAttr spec "name";
            vcpu = spec.vcpu or 2;
            memoryMiB = spec.memoryMiB or 2304;
            homeDiskMiB = spec.homeDiskMiB or 16384;
            mac = requireAttr spec "mac";
            vsockCid = requireAttr spec "vsockCid";
            machineId = requireAttr spec "machineId";

            ipv4 = {
              address = requireAttr spec "ipv4";
              prefixLength = network.prefixLength or 24;
              gateway =
                network.gateway
                or (throw "sandcastle: sandbox build input is missing network.gateway");
            };
            nameservers = network.nameservers or [];

            packageAttrs = spec.packages or [];
            extraPackages = map (resolvePackage pkgs) (spec.packages or []);
            agentPackages = map (resolveAgent pkgs) (spec.agents or []);

            # The public half of the host's SSH control key. Absent only when
            # a runner is built for evaluation coverage rather than for use.
            authorizedKeys = spec.authorizedKeys or [];
          };
        })
      ];
    };

  runnerFromSpec = spec: (systemFromSpec spec).config.microvm.declaredRunner;

  # The CLI copies a build input into the Nix store and passes that store
  # path here. The document is a sandbox specification plus the host network
  # parameters the guest needs but the specification deliberately does not
  # persist.
  fromFile = file: builtins.fromJSON (builtins.readFile file);
in {
  inherit systemFromSpec runnerFromSpec;

  runnerFromSpecFile = file: runnerFromSpec (fromFile file);
  systemFromSpecFile = file: systemFromSpec (fromFile file);
  toplevelFromSpec = spec: (systemFromSpec spec).config.system.build.toplevel;
}
