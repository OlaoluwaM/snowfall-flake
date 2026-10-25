{
  stdenvNoCC,
  replaceVarsWith,
  gum,
  jq,
  findutils,
  nixos-option,
  writeShellApplication,
  ...
}:

let
  substitute = args: builtins.readFile (replaceVarsWith args);

  flake-ref = writeShellApplication {
    name = "flake-ref";
    text = builtins.readFile ./flake-ref.sh;
    runtimeInputs = [ jq ];
  };
  filter-flake = writeShellApplication {
    name = "filter-flake";
    text = builtins.readFile ./filter-flake.sh;
    runtimeInputs = [ flake-ref ];
  };
  filter-flakes = writeShellApplication {
    name = "filter-flakes";
    text = builtins.readFile ./filter-flakes.sh;
    runtimeInputs = [
      filter-flake
      findutils
    ];
  };
  get-registry-flakes = writeShellApplication {
    name = "get-registry-flakes";
    text = builtins.readFile ./get-registry-flakes.sh;
  };
in
(writeShellApplication {
  name = "flake";
  text = substitute {
    src = ./flake.sh;

    replacements = {
      help = ./help;
      system = stdenvNoCC.hostPlatform.system;
      isDarwin = if stdenvNoCC.hostPlatform.isDarwin then "true" else "false";
    };
  };
  runtimeInputs = [
    gum
    jq
    flake-ref
    filter-flakes
    get-registry-flakes
    nixos-option
  ];
}).overrideAttrs
  (old: {
    buildCommand = old.buildCommand + ''
      install -Dm644 ${
        replaceVarsWith {
          src = ./_flake;
          replacements.jq = "${jq}/bin/jq";
        }
      } "$out/share/zsh/site-functions/_flake"
    '';
  })
