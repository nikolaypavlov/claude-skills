#!/bin/bash
# Worktree setup for autoresearch researchers.
# Reads JSON config from stdin, creates a git worktree, symlinks directories,
# creates output directories, and optionally runs a setup command.
#
# Input JSON (stdin):
#   {
#     "worktree_path": ".claude/worktrees/gpu-0",  (required)
#     "base_branch": "main",                        (required)
#     "symlink_dirs": ["datasets"],                  (optional)
#     "create_dirs": ["models/pytorch", "experiments"], (optional)
#     "setup_command": "uv sync --frozen --extra train" (optional)
#   }
#
# Output: absolute path to created worktree

set -euo pipefail

INPUT=$(cat)
WORKTREE_PATH=$(echo "$INPUT" | python3 -c "import json,sys; print(json.load(sys.stdin)['worktree_path'])")
BASE_BRANCH=$(echo "$INPUT" | python3 -c "import json,sys; print(json.load(sys.stdin)['base_branch'])")
SYMLINK_DIRS=$(echo "$INPUT" | python3 -c "import json,sys; print('\n'.join(json.load(sys.stdin).get('symlink_dirs', [])))")
CREATE_DIRS=$(echo "$INPUT" | python3 -c "import json,sys; print('\n'.join(json.load(sys.stdin).get('create_dirs', [])))")
SETUP_CMD=$(echo "$INPUT" | python3 -c "import json,sys; print(json.load(sys.stdin).get('setup_command', ''))")

REPO_ROOT=$(git rev-parse --show-toplevel)

# Make worktree_path absolute if relative
if [[ "$WORKTREE_PATH" != /* ]]; then
    WORKTREE_PATH="$REPO_ROOT/$WORKTREE_PATH"
fi

# Create branch name from worktree directory name
BRANCH_NAME="worktree-$(basename "$WORKTREE_PATH")"

# Remove existing worktree if it exists
if [ -d "$WORKTREE_PATH" ]; then
    git worktree remove "$WORKTREE_PATH" --force 2>/dev/null || true
fi

# Remove branch if it exists
git branch -D "$BRANCH_NAME" 2>/dev/null || true

# Create worktree
git worktree add "$WORKTREE_PATH" -b "$BRANCH_NAME" "$BASE_BRANCH"

# Symlink directories from main repo
if [ -n "$SYMLINK_DIRS" ]; then
    while IFS= read -r dir; do
        [ -z "$dir" ] && continue
        if [ -e "$REPO_ROOT/$dir" ]; then
            ln -sfn "$REPO_ROOT/$dir" "$WORKTREE_PATH/$dir"
        else
            echo "WARNING: symlink source $REPO_ROOT/$dir does not exist" >&2
        fi
    done <<< "$SYMLINK_DIRS"
fi

# Create output directories
if [ -n "$CREATE_DIRS" ]; then
    while IFS= read -r dir; do
        [ -z "$dir" ] && continue
        mkdir -p "$WORKTREE_PATH/$dir"
    done <<< "$CREATE_DIRS"
fi

# Run setup command if provided
if [ -n "$SETUP_CMD" ]; then
    (cd "$WORKTREE_PATH" && eval "$SETUP_CMD" 2>&1) || {
        echo "WARNING: setup command failed, retrying once..." >&2
        sleep 2
        (cd "$WORKTREE_PATH" && eval "$SETUP_CMD" 2>&1) || {
            echo "WARNING: setup command failed on retry" >&2
        }
    }
fi

echo "$WORKTREE_PATH"
