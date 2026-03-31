---
description: "Launch autonomous parallel GPU optimization with coordinated researcher agents"
argument-hint: "[path-to-autoresearch.yaml]"
allowed-tools: ["Bash", "Read", "Write", "Glob", "Grep", "Agent", "TeamCreate", "SendMessage", "TaskCreate", "TaskUpdate", "TaskGet", "TaskList"]
model: opus
---

# /autoresearch - Autonomous Parallel GPU Optimization

You are an orchestrator for autonomous hyperparameter and model optimization using parallel GPU researchers.

## Phase 1: Locate and Parse Config

1. If `$ARGUMENTS` is provided, use it as the path to the config file
2. Otherwise, look for `autoresearch.yaml` in the project root (current working directory)
3. If not found, display usage help and stop:

```
No autoresearch.yaml found.

Create an autoresearch.yaml in your project root. Example:

  training_command: |
    cd {worktree_path} && CUDA_VISIBLE_DEVICES={gpu_id} uv run python train.py \
      --output-json {metrics_file}
  metric:
    name: val_acc_top5
    direction: higher
  mutable_files:
    - scripts/train.py
    - src/model.py

See the config schema reference for full options.
```

4. Read and parse the YAML config file using Python:

```bash
python3 -c "
import yaml, json, sys
with open(sys.argv[1]) as f:
    config = yaml.safe_load(f)
# Validate required fields
required = ['training_command', 'metric', 'mutable_files']
missing = [k for k in required if k not in config]
if missing:
    print(f'ERROR: Missing required fields: {missing}', file=sys.stderr)
    sys.exit(1)
if 'name' not in config.get('metric', {}):
    print('ERROR: metric.name is required', file=sys.stderr)
    sys.exit(1)
if 'direction' not in config.get('metric', {}):
    print('ERROR: metric.direction is required', file=sys.stderr)
    sys.exit(1)
print(json.dumps(config, indent=2))
" "$CONFIG_PATH"
```

## Phase 2: Validate Environment

1. **GPU availability**: Run `nvidia-smi -L` and count available GPUs
2. **Agent Teams**: Verify `CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS=1` is set (check env)
3. **Mutable files**: Verify each file in `mutable_files` exists
4. **Training command**: Verify the training script referenced in `training_command` exists
5. **Setup command**: If `setup_command` is specified, note it for worktree setup

If any validation fails, report the issue clearly and stop.

## Phase 3: Determine Researcher Count

- If `num_researchers` is set in config, use that
- Otherwise, use the number of GPUs detected by `nvidia-smi -L`
- Cap at available GPU count (one researcher per GPU)

## Phase 4: Delegate to Lead Skill

Load the lead coordination skill and pass the parsed config as context:

Read `@${CLAUDE_PLUGIN_ROOT}/skills/autoresearch/SKILL.md` and follow its instructions with the parsed config.

Pass to the skill:
- Full parsed config object
- Number of researchers
- Absolute path to project root
- Git branch name (from `git branch --show-current`)
- Plugin root path (`${CLAUDE_PLUGIN_ROOT}`)

The skill handles worktree creation, researcher spawning, coordination, and session management.
