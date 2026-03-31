# autoresearch.yaml Config Schema

## Required Fields

### `training_command` (string)

Template for the training command. Supports these placeholders:
- `{worktree_path}` - absolute path to the researcher's worktree
- `{gpu_id}` - GPU index (0, 1, 2, ...)
- `{metrics_file}` - path where training should write metrics JSON

The command should:
- cd to the worktree first
- Set `CUDA_VISIBLE_DEVICES` to the GPU
- Write metrics to the specified output file
- Train for a short duration (1 epoch recommended for fast iteration)

### `metric` (object)

- `name` (string, required) - metric name to optimize, must match a key in the metrics JSON output
- `direction` (string, required) - `higher` or `lower`

### `mutable_files` (list of strings)

Files that researchers are allowed to edit. Paths relative to project root.
Keep this list small and focused - only files that contain training logic,
model architecture, or hyperparameters.

## Optional Fields

### `constraints` (list of strings)

Immutable rules that researchers must follow. These are domain-specific
constraints that should never be violated, regardless of what experiments try.

Example:
```yaml
constraints:
  - "Sample rate must remain 8000 Hz"
  - "Backbone features: 1408-dim (EfficientNet-B2), do not change"
  - "Max audio duration: 15 seconds"
```

### `symlink_dirs` (list of strings)

Directories to symlink from the main repo into each worktree. Use this for
large datasets or model weights that shouldn't be copied.

Example: `["datasets", "pretrained"]`

### `create_dirs` (list of strings)

Directories to create in each worktree (for outputs).

Example: `["models/pytorch", "experiments"]`

### `setup_command` (string)

Command to run in each worktree after creation (dependency installation).
Runs with cwd set to the worktree.

Example: `"uv sync --frozen --extra train"`

### `base_branch` (string)

Git branch to base worktrees on. Defaults to the current branch.

### `num_researchers` (integer)

Number of parallel researchers to spawn. Defaults to the number of GPUs
detected by `nvidia-smi -L`. Each researcher gets one GPU.

### `max_experiments_per_researcher` (integer)

Maximum experiments each researcher should run before stopping. Default: 10.

### `ideas` (list of strings)

Exploration hypotheses to assign to researchers. The lead assigns one idea
per researcher initially, then generates new ideas based on results.

If fewer ideas than researchers, remaining researchers propose their own
after reading the mutable files.

### `context` (string)

Additional context for researchers - architecture description, past results,
domain knowledge, or anything that helps them make informed experiment choices.

## Complete Example (Audio Dedup)

```yaml
training_command: |
  cd {worktree_path} && CUDA_VISIBLE_DEVICES={gpu_id} uv run python scripts/train_audio_embeddings.py \
    --data-dir ./datasets/audio/train/ \
    --output-dir ./models/ \
    --epochs 1 \
    --batch-size 32 \
    --bf16 \
    --no-wandb \
    --output-json {metrics_file}

metric:
  name: val_acc_top5
  direction: higher

mutable_files:
  - scripts/train_audio_embeddings.py
  - src/strybo_dedup/audio/model.py
  - src/strybo_dedup/audio/constants.py

constraints:
  - "Sample rate: 8000 Hz"
  - "Mel spectrogram: n_fft=1024, hop=512, n_mels=224, f_min=20, f_max=4000"
  - "Max duration: 15 seconds"
  - "Backbone features: 1408-dim (EfficientNet-B2)"
  - "Backbone features used for inference (not projection head)"

symlink_dirs:
  - datasets

create_dirs:
  - models/pytorch
  - experiments

setup_command: "uv sync --frozen --extra train"

base_branch: feature/autoresearch

ideas:
  - "Learning rate: try higher lr (3e-4, 5e-4, 1e-3) with cosine warmup"
  - "Batch size: larger = more negatives (try 64, 96, 128 with lr scaling)"
  - "Temperature: explore range 0.03-0.2 (current: 0.07)"
  - "Augmentation: adjust probabilities, add new augmentation types"
  - "Optimizer: LARS or LAMB for large-batch contrastive learning"
  - "Projection head: add BatchNorm, change dimensions (128, 512), add layers"
  - "Loss variants: hard negative mining, decoupled contrastive loss"
  - "Weight decay tuning (1e-4 to 1e-2 range)"
  - "Gradient clipping strategies"
  - "Learning rate warmup schedules (linear, exponential)"

context: |
  Architecture: EfficientNet-B2 backbone + SimCLR contrastive learning.
  Best model: 0.954 F1@0.5. Current metric after 1 epoch: ~0.42 val_acc_top5.
  NT-Xent loss with temperature=0.07.
```

## Minimal Example

```yaml
training_command: |
  cd {worktree_path} && CUDA_VISIBLE_DEVICES={gpu_id} python train.py \
    --output-json {metrics_file}

metric:
  name: val_loss
  direction: lower

mutable_files:
  - train.py
  - model.py
```
