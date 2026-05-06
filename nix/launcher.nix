{ lib
, beamPackages
, sqlite
, gnumake
, pkg-config
, stdenv
, fetchMixDepsHash ? null
}:

let
  pname = "agent-sandcastle-launcher";
  version = "0.1.0";

  src = lib.cleanSourceWith {
    name = "agent-sandcastle-launcher-source";
    src = ../launcher;
    filter = path: type:
      let base = baseNameOf (toString path); in
      !(builtins.elem base [
        "_build"
        ".cache"
        ".elixir_ls"
        ".hex"
        ".mix"
        ".rodney"
        "deps"
      ])
      && !(lib.hasSuffix ".db" base)
      && !(lib.hasSuffix ".db-shm" base)
      && !(lib.hasSuffix ".db-wal" base);
  };

  mixFodDeps = beamPackages.fetchMixDeps {
    pname = "${pname}-mix-deps";
    inherit src version;
    hash = if fetchMixDepsHash == null
      then lib.fakeHash
      else fetchMixDepsHash;
  };
in
beamPackages.mixRelease {
  inherit pname version src mixFodDeps;

  mixReleaseName = "agent_sandcastle_launcher";

  nativeBuildInputs = [ gnumake pkg-config ];
  buildInputs = [ sqlite ];

  # Force exqlite to compile its NIF from source against the staged Mix deps —
  # fetchMixDepsHash provides the source tree but not network access, so the
  # cc_precompiler download path would fail mid-build. ELIXIR_MAKE_FORCE_BUILD
  # is the upstream-supported override.
  ELIXIR_MAKE_FORCE_BUILD = "true";

  # elixir_make's `cache_dir/0` resolves XDG_CACHE_HOME (or $HOME/.cache).
  # Inside the Nix sandbox HOME is `/homeless-shelter`, so writes fail unless
  # we redirect the cache. preConfigure runs before mixRelease's
  # `mix deps.compile` (which is what triggers exqlite's NIF build).
  preConfigure = ''
    export XDG_CACHE_HOME="$TEMPDIR/.cache"
    mkdir -p "$XDG_CACHE_HOME/elixir_make"
  '';

  # Don't bake a release cookie into the store path. The systemd unit gets a
  # cookie from sops via `RELEASE_COOKIE` instead.
  removeCookie = true;

  meta = with lib; {
    description = "Phoenix LiveView launcher for agent-sandcastle sandboxes";
    license = licenses.asl20;
    platforms = platforms.linux;
    mainProgram = "agent_sandcastle_launcher";
  };
}
