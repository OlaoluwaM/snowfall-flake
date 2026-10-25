# shellcheck shell=bash
full_output=$(nix registry list)

while read -r type _registry_uri flake_uri; do
	if [[ -n $flake_uri && $type != system && $flake_uri != path:/nix/store* ]]; then
		printf '%s\n' "$flake_uri"
	fi
done <<< "$full_output"
