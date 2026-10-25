{
  stdenvNoCC,
  replaceVarsWith,
  gum,
  findutils,
  nixos-option,
  writeShellApplication,
  inputs,
  ...
}:

let
  substitute = args: builtins.readFile (replaceVarsWith args);

  filter-flake = writeShellApplication {
    name = "filter-flake";
    text = builtins.readFile ./filter-flake.sh;
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
writeShellApplication {
  name = "flake";
  text = substitute {
    src = ./flake.sh;

    replacements = {
      help = ./help;
      flakeCompat = inputs.flake-compat;
      isDarwin = if stdenvNoCC.hostPlatform.isDarwin then "true" else "false";
    };
  };
  runtimeInputs = [
    gum
    filter-flakes
    get-registry-flakes
    nixos-option
  ];
}
