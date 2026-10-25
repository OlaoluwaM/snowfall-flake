# shellcheck shell=bash
target=$1
shift

# Each URI stays a single argument, including paths with spaces or shell syntax.
if [[ $# -gt 0 ]]; then
	printf '%s\0' "$@" | xargs -0 -P 10 -I '{}' filter-flake "$target" '{}'
fi
