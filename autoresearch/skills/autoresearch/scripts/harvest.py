#!/usr/bin/env python3
"""Harvest winning experiments from autoresearch worktree branches.

Reads git log from worktree-* branches, parses commit messages for metrics,
ranks experiments, and prints a summary table.

Usage:
    python3 harvest.py
    python3 harvest.py --metric-name val_loss --metric-direction lower
    python3 harvest.py --cherry-pick-top 3
"""

import argparse
import re
import subprocess
import sys


def find_worktree_branches() -> list[str]:
    """Find all worktree-* branches from autoresearch sessions."""
    result = subprocess.run(
        ["git", "branch", "--list", "worktree-*", "--format=%(refname:short)"],
        capture_output=True,
        text=True,
    )
    return [b.strip() for b in result.stdout.strip().splitlines() if b.strip()]


def get_branch_commits(branch: str, base_ref: str, metric_name: str) -> list[dict]:
    """Get experiment commits from a branch since it diverged from base."""
    try:
        result = subprocess.run(
            ["git", "log", f"{base_ref}..{branch}", "--oneline", "--no-decorate"],
            capture_output=True,
            text=True,
            check=True,
        )
    except subprocess.CalledProcessError:
        return []

    commits = []
    pattern = re.compile(rf"{re.escape(metric_name)}=([\d.]+)")

    for line in result.stdout.strip().splitlines():
        if not line:
            continue
        parts = line.split(" ", 1)
        if len(parts) != 2:
            continue
        sha, message = parts

        match = pattern.search(message)
        metric = float(match.group(1)) if match else None

        commits.append(
            {
                "sha": sha,
                "message": message,
                "branch": branch,
                "metric": metric,
            }
        )

    return commits


def print_summary(
    all_commits: list[dict], metric_name: str, higher_is_better: bool
) -> None:
    """Print ranked summary table of all experiments."""
    with_metric = [c for c in all_commits if c["metric"] is not None]
    without_metric = [c for c in all_commits if c["metric"] is None]

    with_metric.sort(key=lambda c: c["metric"], reverse=higher_is_better)

    header = f"{'Rank':<6} {'Branch':<25} {'SHA':<10} {metric_name:<20} {'Description'}"
    print(f"\n{header}")
    print("-" * len(header) + "-" * 40)

    for i, c in enumerate(with_metric, 1):
        desc = c["message"]
        if len(desc) > 50:
            desc = desc[:47] + "..."
        print(f"{i:<6} {c['branch']:<25} {c['sha']:<10} {c['metric']:<20.4f} {desc}")

    if without_metric:
        print(f"\n{len(without_metric)} commits without parseable metrics (skipped)")

    branches = set(c["branch"] for c in all_commits)
    print(
        f"\nTotal: {len(with_metric)} ranked experiments from {len(branches)} branches"
    )


def cherry_pick_top(commits: list[dict], n: int, higher_is_better: bool) -> None:
    """Cherry-pick top N experiments to the current branch."""
    with_metric = sorted(
        [c for c in commits if c["metric"] is not None],
        key=lambda c: c["metric"],
        reverse=higher_is_better,
    )[:n]

    if not with_metric:
        print("No commits with metrics to cherry-pick.")
        return

    print(f"\nCherry-picking top {len(with_metric)} experiments:")
    for c in with_metric:
        print(f"  {c['sha']} ({c['metric']:.4f}) - {c['message'][:60]}")
        result = subprocess.run(
            ["git", "cherry-pick", "--no-commit", c["sha"]],
            capture_output=True,
            text=True,
        )
        if result.returncode != 0:
            print(f"    CONFLICT - skipping: {result.stderr.strip()}")
            subprocess.run(["git", "cherry-pick", "--abort"], capture_output=True)
        else:
            subprocess.run(
                ["git", "commit", "-m", f"cherry-pick: {c['message']}"],
                capture_output=True,
                text=True,
            )
            print("    OK")


def main():
    parser = argparse.ArgumentParser(
        description="Harvest autoresearch experiment results"
    )
    parser.add_argument(
        "--metric-name",
        type=str,
        default="val_acc_top5",
        help="Metric name to parse from commit messages (default: val_acc_top5)",
    )
    parser.add_argument(
        "--metric-direction",
        type=str,
        choices=["higher", "lower"],
        default="higher",
        help="Whether higher or lower metric values are better (default: higher)",
    )
    parser.add_argument(
        "--base-ref",
        type=str,
        default=None,
        help="Base ref to compare branches against (default: current branch)",
    )
    parser.add_argument(
        "--cherry-pick-top",
        type=int,
        default=None,
        help="Cherry-pick top N experiments to current branch",
    )
    args = parser.parse_args()

    # Default base-ref to current branch
    if args.base_ref is None:
        result = subprocess.run(
            ["git", "branch", "--show-current"],
            capture_output=True,
            text=True,
        )
        args.base_ref = result.stdout.strip() or "main"

    higher_is_better = args.metric_direction == "higher"

    branches = find_worktree_branches()
    if not branches:
        print("No worktree-* branches found.")
        sys.exit(0)

    all_commits = []
    for branch in branches:
        commits = get_branch_commits(branch, args.base_ref, args.metric_name)
        all_commits.extend(commits)
        print(f"Branch {branch}: {len(commits)} experiment commits")

    if not all_commits:
        print("No experiment commits found on any worktree branch.")
        sys.exit(0)

    print_summary(all_commits, args.metric_name, higher_is_better)

    if args.cherry_pick_top:
        cherry_pick_top(all_commits, args.cherry_pick_top, higher_is_better)


if __name__ == "__main__":
    main()
