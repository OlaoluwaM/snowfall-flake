{
  description = "Snowfall Flake";

  inputs = {
    nixpkgs.url = "github:nixos/nixpkgs/nixos-26.05";

    snowfall-lib = {
      # Current Snowfall Lib supports the Nixpkgs foldr and hostPlatform APIs.
      url = "github:snowfallorg/lib";
      inputs.nixpkgs.follows = "nixpkgs";
    };
  };

  outputs =
    inputs:
    inputs.snowfall-lib.mkFlake {
      inherit inputs;
      src = ./.;

      snowfall = {
        namespace = "snowfallorg";
      };

      alias.packages.default = "flake";
    };
}
