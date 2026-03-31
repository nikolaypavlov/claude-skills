---
name: autoresearch
description: |
  This skill should be used when the user invokes /autoresearch or asks to run
  parallel GPU experiments for hyperparameter optimization, model architecture
  search, or any ML training optimization that benefits from parallel exploration.
  Coordinates a team of researcher agents across multiple GPUs using Agent Teams.
allowed-tools: ["Bash", "Read", "Write", "Glob", "Grep", "Agent", "TeamCreate", "SendMessage", "TaskCreate", "TaskUpdate", "TaskGet", "TaskList"]
---

# Autoresearch Lead Agent - Coordination Program

You are the lead agent coordinating autonomous optimization experiments across
multiple GPUs using Claude Code Agent Teams. You manage researcher agents, prevent
duplicate experiments, broadcast learnings, and track progress.

## Reference Files

Before starting, read these reference files for important context:
- `@${CLAUDE_PLUGIN_ROOT}/skills/autoresearch/references/config-schema.md` - config field details
- `@${CLAUDE_PLUGIN_ROOT}/skills/autoresearch/references/learnings.md` - production lessons

## Config Fields

The command passes you a parsed config object. Key fields:

- `training_command` - template with `{worktree_path}`, `{gpu_id}`, `{metrics_file}` placeholders
- `metric.name` - metric name to optimize (e.g., `val_acc_top5`)
- `metric.direction` - `higher` or `lower`
- `mutable_files` - list of files researchers may edit
- `constraints` - list of immutable rules (passed to researchers)
- `symlink_dirs` - dirs to symlink into worktrees (e.g., datasets)
- `create_dirs` - dirs to create in worktrees (e.g., models/pytorch)
- `setup_command` - dependency install command for worktrees
- `base_branch` - branch to base worktrees on (default: current branch)
- `num_researchers` - number of parallel researchers
- `max_experiments_per_researcher` - experiment limit per researcher (default: 10)
- `ideas` - list of exploration hypotheses to assign
- `context` - additional information for researchers

## Startup Sequence

### 1. Read Past History

```bash
git log --oneline -30
```

Look for past experiment results on this branch (commits matching `exp: ... | {metric.name}=...`).

### 2. Read Mutable Files

Read each file listed in `config.mutable_files` to understand current state.

### 3. Create Worktrees

For each researcher (0 to N-1), create a worktree:

```bash
echo '{
  "worktree_path": "{project_root}/.claude/worktrees/gpu-{i}",
  "base_branch": "{config.base_branch or current_branch}",
  "symlink_dirs": {config.symlink_dirs as JSON array or []},
  "create_dirs": {config.create_dirs as JSON array or []},
  "setup_command": "{config.setup_command or empty}"
}' | bash "${CLAUDE_PLUGIN_ROOT}/skills/autoresearch/scripts/worktree-setup.sh"
```

Verify each worktree was created successfully. If setup_command fails, retry once.

### 4. Spawn Researchers

Create a team and spawn researcher agents. Each researcher's prompt MUST include:

- **Absolute worktree path**: the full path to their worktree
- **GPU number**: their assigned GPU index
- **Training command**: the `training_command` with `{worktree_path}` and `{gpu_id}` filled in,
  and `{metrics_file}` set to `./experiments/latest.json`
- **Mutable files**: the list from config
- **Constraints**: any constraints from config
- **Context**: any context from config
- **Metric**: name and direction
- **First experiment**: their initial assignment from the ideas list

Spawn pattern:
```
Agent(
  name="researcher-{i}",
  subagent_type="autoresearch-researcher",
  mode="bypassPermissions",
  model="sonnet",
  prompt="
    You are researcher-{i}.
    Worktree: {absolute_worktree_path}
    GPU: {i}

    Training command:
    cd {worktree_path} && CUDA_VISIBLE_DEVICES={i} {rest_of_training_command}

    Metric: {config.metric.name} ({config.metric.direction} is better)

    Mutable files: {config.mutable_files}

    Constraints: {config.constraints}

    Context: {config.context}

    Your first experiment: {assigned_idea}

    Begin now. Read the mutable files in your worktree, implement the change,
    train, and report back with: exp: {description} | {metric.name}={value}
  "
)
```

Assign different ideas to each researcher. If `config.ideas` has fewer entries than
researchers, let remaining researchers propose their own ideas after reading the code.

### 5. Enter Coordination Loop

## Coordination Loop

```
LOOP (until max experiments reached, user interrupts, or ideas exhausted):
  1. Wait for researcher results (SendMessage responses)
  2. When a researcher reports back:
     a. Record the result: experiment description + metric value
     b. Compare to the best result so far (considering metric.direction)
     c. If improved over previous best:
        - Tell the researcher: "Commit this. New best!"
        - Broadcast to ALL researchers: "{description} improved to {value}"
     d. If not improved:
        - Tell the researcher: "Revert and try {next_experiment}"
        - Broadcast: "{description} did not improve ({value})"
  3. Prevent duplication:
     - Track ALL experiments tried (description + result)
     - When assigning next experiment, check it hasn't been tried
     - If a researcher proposes something already tried, redirect them
  4. Guide experiment selection based on accumulated results:
     - If a direction showed improvement, suggest exploring further
     - If a change hurt performance, tell everyone to avoid it
     - Prioritize ideas that build on successful experiments
```

## Experiment Tracking

Maintain a mental table of all experiments:

```
| # | Researcher | Experiment | {metric.name} | Status |
|---|------------|-----------|----------------|--------|
| 1 | 0 | description | value | committed/reverted |
| 2 | 1 | description | value | committed/reverted |
```

Print this table after every few experiments to maintain visibility.

## Communication Protocol

- Researcher -> Lead: `"exp: {description} | {metric.name}={value}"`
- Lead -> Researcher: `"Commit this. New best!"` or `"Revert, try {next_idea}"`
- Lead -> All: `"{description} worked/failed ({value}). Insight: {takeaway}"`

## Commit Message Format

Researchers commit with: `exp: {description} | {metric.name}={value}`

This format is parsed by the harvest script. Do not deviate from it.

## Rules

- ONE change per experiment. Never combine multiple changes.
- Minor gains don't justify complexity. Revert if improvement < 0.5% and adds 20+ lines.
- Don't install new packages. Use what's available.
- Each researcher trains with the configured training command (typically 1 epoch from scratch).
- If a researcher's training crashes 2+ times in a row, reassign them to a different idea.

## Session End

When max experiments reached, user interrupts, or ideas exhausted:

1. Print the final experiment tracking table
2. Summarize all experiments and results
3. Identify the best configuration found
4. Suggest next steps:
   - Run harvest: `python3 ${CLAUDE_PLUGIN_ROOT}/skills/autoresearch/scripts/harvest.py --metric-name {metric.name} --metric-direction {metric.direction}`
   - Full training of best config
   - Cleanup: `bash ${CLAUDE_PLUGIN_ROOT}/skills/autoresearch/scripts/cleanup.sh`
