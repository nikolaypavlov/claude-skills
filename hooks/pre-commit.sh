#!/bin/bash
set -uo pipefail

# Pre-commit hook: lint staged Python and YAML files before git commit.
# Runs as PreToolUse on Bash -- intercepts git commit commands,
# auto-fixes what it can, and blocks the commit if issues remain.

input=$(cat)

command_str=$(echo "$input" | jq -r '.tool_input.command // empty')

# Not a bash command with input
[[ -z "$command_str" ]] && exit 0

# Not a git commit command (handles git -C <path> commit, git commit, etc.)
[[ "$command_str" != *git*commit* ]] && exit 0

# uv not available
command -v uv &>/dev/null || exit 0

# Get staged files (exclude deleted)
staged_files=$(git diff --cached --name-only --diff-filter=d 2>/dev/null)
[[ -z "$staged_files" ]] && exit 0

py_files=$(echo "$staged_files" | grep '\.py$' || true)
yaml_files=$(echo "$staged_files" | grep '\.ya\?ml$' || true)

# Nothing to lint
[[ -z "$py_files" && -z "$yaml_files" ]] && exit 0

has_issues=false

# --- Python files ---
if [[ -n "$py_files" ]]; then
  py_array=()
  while IFS= read -r f; do
    [[ -f "$f" ]] && py_array+=("$f")
  done <<< "$py_files"

  if [[ ${#py_array[@]} -gt 0 ]]; then
    # Auto-fix: ruff check + format (stderr visible for diagnostics)
    uvx ruff check --fix --extend-select I --quiet "${py_array[@]}" || true
    uvx ruff format --quiet "${py_array[@]}" || true

    # Re-stage auto-fixed files
    git add "${py_array[@]}" 2>/dev/null || true

    # Final lint check (capture stdout only)
    ruff_issues=$(uvx ruff check --extend-select I --quiet "${py_array[@]}") || true
    if [[ -n "$ruff_issues" ]]; then
      echo "ruff: lint issues in staged Python files:" >&2
      echo "$ruff_issues" >&2
      has_issues=true
    fi

    # Type check (ty is much faster than mypy -- written in Rust by Astral)
    ty_issues=$(uvx ty check --ignore unresolved-import "${py_array[@]}" 2>&1)
    ty_exit=$?
    if [[ $ty_exit -ne 0 && -n "$ty_issues" ]]; then
      echo "ty: type errors in staged Python files:" >&2
      echo "$ty_issues" >&2
      has_issues=true
    fi
  fi
fi

# --- YAML files ---
if [[ -n "$yaml_files" ]]; then
  while IFS= read -r f; do
    [[ ! -f "$f" ]] && continue
    yaml_issues=$(uvx yamllint -d '{extends: default, rules: {line-length: {max: 120}}}' "$f" 2>&1) || true
    if [[ -n "$yaml_issues" ]]; then
      echo "yamllint: issues in $f:" >&2
      echo "$yaml_issues" >&2
      has_issues=true
    fi
  done <<< "$yaml_files"
fi

if [[ "$has_issues" == true ]]; then
  echo "pre-commit: fix the issues above before committing." >&2
  exit 2
fi

exit 0
