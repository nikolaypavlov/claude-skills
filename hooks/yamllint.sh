#!/bin/bash
set -uo pipefail

# Yamllint for YAML files.
# Runs via uvx after Write/Edit operations. Exits early if:
# - File is not .yaml or .yml
# - uv is not installed

input=$(cat)

file_path=$(echo "$input" | jq -r '.tool_input.file_path // empty')

# --- Quick exits ---

[[ -z "$file_path" ]] && exit 0
[[ "$file_path" != *.yaml && "$file_path" != *.yml ]] && exit 0
[[ ! -f "$file_path" ]] && exit 0
command -v uv &>/dev/null || exit 0

# --- Run yamllint ---

issues=$(uvx yamllint -d '{extends: default, rules: {line-length: {max: 120}}}' "$file_path" 2>&1) || true

if [[ -n "$issues" ]]; then
  echo "yamllint: issues in $(basename "$file_path"):" >&2
  echo "$issues" >&2
  exit 2
fi

exit 0
