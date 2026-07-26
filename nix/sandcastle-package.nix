{
  lib,
  stdenvNoCC,
  makeWrapper,
  python3,
  coreutils,
  nix,
  openssh,
  systemd,
}: let
  # Everything the CLI shells out to. Keeping it explicit means a sandcastle
  # invocation does not depend on whatever happens to be on the operator's
  # PATH under sudo. `systemd` supplies systemctl and journalctl; `openssh`
  # supplies the ssh and ssh-keygen that `sandcastle ssh` uses over VSOCK.
  runtimeInputs = [
    coreutils
    nix
    openssh
    systemd
  ];
in
  stdenvNoCC.mkDerivation (finalAttrs: {
    pname = "sandcastle";
    version = "0.1.0";

    src = lib.fileset.toSource {
      root = ../.;
      fileset = lib.fileset.unions [
        ../sandcastle
        ../tests
      ];
    };

    strictDeps = true;
    nativeBuildInputs = [makeWrapper python3];

    dontConfigure = true;
    dontBuild = true;

    doCheck = true;
    checkPhase = ''
      runHook preCheck
      python3 -m unittest discover --start-directory tests --top-level-directory . --verbose
      runHook postCheck
    '';

    installPhase = ''
      runHook preInstall

      site="$out/${python3.sitePackages}"
      install -d "$site"
      cp -r sandcastle "$site/sandcastle"
      python3 -m compileall -q "$site/sandcastle"

      makeWrapper ${lib.getExe python3} "$out/bin/sandcastle" \
        --add-flags "-m sandcastle" \
        --prefix PYTHONPATH : "$site" \
        --prefix PATH : ${lib.makeBinPath runtimeInputs}

      runHook postInstall
    '';

    meta = {
      description = "CLI for managing isolated development MicroVMs on a NixOS host";
      mainProgram = "sandcastle";
      license = lib.licenses.asl20;
      platforms = lib.platforms.linux;
    };
  })
