# shellcheck shell=bash
ref=$1
local_path=${ref#path:}

# Let jq encode URI-reserved characters, while retaining path separators.
# Already encoded references and remote URLs pass through unchanged.
if [[ -d $local_path ]]; then
	local_path=$(cd -- "$local_path" && pwd -P)
	printf 'path:%s\n' "$(jq -nr --arg path "$local_path" '$path | @uri | gsub("%2F"; "/")')"
else
	printf '%s\n' "$ref"
fi
