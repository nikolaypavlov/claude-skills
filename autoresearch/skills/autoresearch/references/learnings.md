# Production Learnings from Autoresearch

Lessons from real autoresearch sessions. The lead agent and researchers should
internalize these to avoid known pitfalls.

## Worktree Isolation

Agent Teams `isolation: worktree` in Claude Code does not create real git worktrees
that persist between agent invocations. You MUST pre-create worktrees manually using
`worktree-setup.sh` and pass the absolute path to each researcher in their prompt.

Each researcher must always `cd {worktree_path}` before any file operation or command.
Never rely on the current working directory being correct.

## Researcher Configuration

- Researchers need `mode: bypassPermissions` to avoid permission prompts during training
- Use `model: sonnet` for researchers - fast and capable enough for experiment execution
- The lead should use `model: opus` for strategic coordination decisions

## Dependency Installation in Worktrees

`uv sync` or `pip install` can fail in worktrees due to lock file conflicts or
missing symlinks. Researchers should:
1. Try the setup command once during worktree creation
2. If it fails during training, retry once
3. If it still fails, report to the lead rather than trying to fix it themselves

## Training Flags

- Use `--no-wandb` or equivalent to avoid authentication issues in worktrees
  (W&B/MLflow may not have credentials configured in the worktree env)
- Always write metrics to a JSON file (`--output-json`) rather than parsing stdout
- Use short training runs (1 epoch) for fast iteration; full training comes after
  the best config is identified

## Experiment Design

- **Larger batch sizes are not always better**: Larger batch = fewer gradient steps
  per epoch. For 1-epoch experiments, this means less learning. A batch size of 32
  with more gradient steps often outperforms batch size 128 with fewer steps.
- **Baselines are hard to beat**: Well-tuned models resist single-parameter changes.
  Don't expect every experiment to improve. A session where 2 out of 10 experiments
  improve is a good session.
- **One change at a time**: Never combine multiple changes in a single experiment.
  If it improves, you don't know which change helped. If it hurts, you can't isolate
  the problem.
- **Build on success**: When an experiment improves, the next experiments should
  explore variations of that successful change rather than trying unrelated ideas.

## Metric Reporting

- Commit message format is critical: `exp: {description} | {metric_name}={value}`
- The harvest script parses this exact format with regex
- Always include the metric value even for failed experiments (report the actual
  value, not "failed")
- If training truly crashes (no metric produced), report the error message instead

## Session Management

- A typical session runs 8-15 experiments across 4 GPUs in about 1-2 hours
- The lead should summarize progress every 4-5 experiments
- If all researchers converge on the same conclusion (e.g., "lr changes don't help"),
  pivot to a different hypothesis category
- Don't chase diminishing returns - if the last 4 experiments all failed to improve,
  consider ending the session
