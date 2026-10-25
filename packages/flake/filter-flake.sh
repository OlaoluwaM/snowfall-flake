# shellcheck shell=bash
ref=$(flake-ref "$2")
# Registry discovery may include inaccessible or unlocked flakes. Skip those,
# but keep all values out of the Nix source expression.
# Nix attribute interpolation must reach Nix unchanged.
# shellcheck disable=SC2016
if has_target=$(SNOWFALL_REF="$ref" SNOWFALL_OUTPUT="$1" nix eval --impure --raw --expr '
	let
		flake = builtins.getFlake (builtins.getEnv "SNOWFALL_REF");
		output = builtins.getEnv "SNOWFALL_OUTPUT";
	in if builtins.attrNames (flake.${output} or {}) != [] then "true" else "false"
' 2>/dev/null) && [[ $has_target == true ]]; then
	printf '%s\n' "$ref"
fi
