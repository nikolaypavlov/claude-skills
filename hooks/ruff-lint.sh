#!/bin/bash
set -uo pipefail

# Ruff linting, formatting, and import sorting for Python files.
# Runs via uvx after Write/Edit operations. Exits early if:
# - File is not .py
# - uv is not installed
# - No Python project markers found (pyproject.toml, setup.py, setup.cfg)

input=$(cat)

file_path=$(echo "$input" | jq -r '.tool_input.file_path // empty')

# --- Quick exits (cheapest checks first) ---

# No file path
[[ -z "$file_path" ]] && exit 0

# Not a Python file
[[ "$file_path" != *.py ]] && exit 0

# File doesn't exist (deleted or moved)
[[ ! -f "$file_path" ]] && exit 0

# uv not available
command -v uv &>/dev/null || exit 0

# Not a Python project
project_dir="${CLAUDE_PROJECT_DIR:-.}"
[[ -f "$project_dir/pyproject.toml" ]] ||
  [[ -f "$project_dir/setup.py" ]] ||
  [[ -f "$project_dir/setup.cfg" ]] || exit 0

# --- Run ruff ---

# Fix auto-fixable issues and sort imports
uvx ruff check --fix --extend-select I --quiet "$file_path" 2>/dev/null || true

# Format
uvx ruff format --quiet "$file_path" 2>/dev/null || true

# Final check: report remaining issues to Claude
issues=$(uvx ruff check --extend-select I "$file_path" 2>/dev/null) || true

if [[ -n "$issues" ]]; then
  echo "ruff: issues in $(basename "$file_path"):" >&2
  echo "$issues" >&2
  exit 2
fi

exit 0
