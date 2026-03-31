#!/bin/bash
# Remove autoresearch worktrees and prune branches.
# Safe to run multiple times.

set -euo pipefail

echo "Removing autoresearch worktrees..."

# Remove worktrees in .claude/worktrees/
git worktree list | grep '\.claude/worktrees' | awk '{print $1}' | while read -r wt; do
    echo "  Removing worktree: $wt"
    git worktree remove "$wt" --force 2>/dev/null || true
done

# Prune stale worktree references
git worktree prune

# Remove worktree-* branches
echo "Removing worktree branches..."
git branch --list 'worktree-*' --format='%(refname:short)' | while read -r branch; do
    echo "  Deleting branch: $branch"
    git branch -D "$branch" 2>/dev/null || true
done

echo "Cleanup complete."
