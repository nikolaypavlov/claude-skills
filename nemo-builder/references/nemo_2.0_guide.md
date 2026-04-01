# NeMo 2.0: Complete Guide and Migration

This guide explains what's new in NeMo 2.0, how it differs from NeMo 1.x, and why you should use NeMo 2.0 for all new projects.

**Official Migration Documentation**: `https://docs.nvidia.com/nemo-framework/user-guide/latest/nemo-2.0/migration/index.html`

---

## What is NeMo 2.0?

NeMo 2.0 represents a **fundamental architectural shift** in the NVIDIA NeMo framework, moving from YAML-based configuration to Python-based programmatic setup.

### Key Philosophy Change

**NeMo 1.x approach:**
- Configuration through YAML files
- Declarative, file-based experiment setup
- Limited programmatic control

**NeMo 2.0 approach:**
- Configuration through Python code
- Programmatic, flexible experiment setup
- Full IDE support with type checking and autocomplete

---

## Why Use NeMo 2.0?

### 1. Enhanced Flexibility

**Python-first design** allows dynamic configuration:
```python
# Conditional configuration based on runtime conditions
if num_gpus > 8:
    strategy = nl.MegatronStrategy(tensor_model_parallel_size=4)
else:
    strategy = nl.MegatronStrategy(tensor_model_parallel_size=2)
```

### 2. Better IDE Integration

**Full IDE support:**
- Code completion and IntelliSense
- Type checking and error detection
- Inline documentation
- Refactoring tools

### 3. Easier Extension and Customization

**Programmatic control** enables:
- Custom training loops
- Dynamic data loading
- Conditional logic in configurations
- Easy integration with other libraries

### 4. New NeMo Run Library

**NeMo Run** provides:
- Unified experiment management
- Multi-platform execution (local, SLURM, Kubernetes, cloud)
- Reproducible experiments
- Simplified configuration management

**Documentation**: `https://docs.nvidia.com/nemo/run/latest/index.html`

---

## Key Architectural Changes

### 1. Trainer Configuration

#### NeMo 1.x (YAML):
```yaml
# config.yaml
trainer:
  num_nodes: 16
  devices: 8
  accelerator: gpu
  precision: bf16
  max_steps: 75000
  gradient_clip_val: 1.0
  log_every_n_steps: 10
```

#### NeMo 2.0 (Python):
```python
from nemo import lightning as nl

trainer = nl.Trainer(
    num_nodes=16,
    devices=8,
    accelerator="gpu",
    strategy=strategy,                                  # New: explicit strategy
    plugins=nl.MegatronMixedPrecision(                 # New: precision as plugin
        precision="bf16-mixed"
    ),
    max_steps=75000,
    gradient_clip_val=1.0,
    log_every_n_steps=10,
)
```

**Key differences:**
- `precision: bf16` → `plugins=nl.MegatronMixedPrecision(precision="bf16-mixed")`
- Logger no longer in trainer config
- Strategy explicitly defined

### 2. Experiment Management

#### NeMo 1.x (YAML):
```yaml
# config.yaml
exp_manager:
  exp_dir: /results/my_experiment
  name: llama3_finetune
  create_checkpoint_callback: true
  checkpoint_callback_params:
    monitor: val_loss
    save_top_k: 3
    mode: min
    save_last: true
  resume_if_exists: true
```

#### NeMo 2.0 (Python):
```python
from nemo.lightning.pytorch.callbacks import ModelCheckpoint
from nemo.lightning import NeMoLogger, AutoResume

# Logger
logger = NeMoLogger(
    name="llama3_finetune",
    dir="/results/my_experiment",
)

# Checkpointing
checkpoint_callback = ModelCheckpoint(
    monitor="val_loss",
    save_top_k=3,
    mode="min",
    save_last=True,
)

# Auto-resume
resume = AutoResume(
    resume_if_exists=True,
)

# Pass to trainer
trainer = nl.Trainer(
    logger=logger,
    callbacks=[checkpoint_callback],
    plugins=[resume],
)
```

**Key differences:**
- `exp_manager` split into separate components
- More explicit control over each component
- Easier to customize individual behaviors

### 3. Data Configuration

#### NeMo 1.x (YAML):
```yaml
# config.yaml
model:
  data:
    train_ds:
      file_names: /data/train.jsonl
      global_batch_size: 128
      micro_batch_size: 1
      shuffle: true
    validation_ds:
      file_names: /data/val.jsonl
      global_batch_size: 128
      micro_batch_size: 1
```

#### NeMo 2.0 (Python):
```python
from nemo.collections import llm

# DataModule handles all data configuration
data = llm.SquadDataModule(
    train_path="/data/train.jsonl",
    validation_path="/data/val.jsonl",
    seq_length=4096,
    global_batch_size=128,
    micro_batch_size=1,
    num_workers=4,
)
```

**Key differences:**
- Dedicated `DataModule` classes
- More Pythonic interface
- Easier to create custom data loaders

### 4. Optimizer Configuration

#### NeMo 1.x (YAML):
```yaml
# config.yaml
model:
  optim:
    name: fused_adam
    lr: 1e-5
    weight_decay: 0.01
    betas: [0.9, 0.999]
    sched:
      name: CosineAnnealing
      warmup_steps: 1000
      max_steps: 10000
      min_lr: 1e-6
```

#### NeMo 2.0 (Python):
```python
from nemo import lightning as nl

optim = nl.MegatronOptimizerModule(
    config=nl.OptimizerConfig(
        optimizer="adam",                    # Note: string name, not "fused_adam"
        lr=1e-5,
        weight_decay=0.01,
        betas=(0.9, 0.999),
        bf16=True,
    ),
    lr_scheduler=nl.CosineAnnealingScheduler(
        warmup_steps=1000,
        max_steps=10000,
        min_lr=1e-6,
    ),
)
```

**Key differences:**
- `OptimizerConfig` from Megatron-Core
- Separate scheduler classes
- String optimizer names (e.g., "adam" instead of "fused_adam")

### 5. Model Configuration

#### NeMo 1.x (YAML):
```yaml
# config.yaml
model:
  name: llama3_8b
  num_layers: 32
  hidden_size: 4096
  num_attention_heads: 32
  ffn_hidden_size: 14336
  # ... many more parameters
```

#### NeMo 2.0 (Python):
```python
from nemo.collections import llm

# Use predefined config
model = llm.Llama3Config8B()

# Or customize
model = llm.Llama3Config8B(
    num_layers=32,
    hidden_size=4096,
    num_attention_heads=32,
    ffn_hidden_size=14336,
)
```

**Key differences:**
- Predefined model configs available
- Type-safe configuration
- Easy to extend and customize

---

## Complete Migration Example

### NeMo 1.x Full YAML Configuration

```yaml
# config.yaml
trainer:
  num_nodes: 1
  devices: 8
  accelerator: gpu
  precision: bf16
  max_steps: 10000
  log_every_n_steps: 10
  val_check_interval: 500

exp_manager:
  exp_dir: /results/llama3_finetune
  name: my_experiment
  create_checkpoint_callback: true
  checkpoint_callback_params:
    save_top_k: 3
  resume_if_exists: true

model:
  name: llama3_8b

  data:
    train_ds:
      file_names: /data/train.jsonl
      global_batch_size: 128
    validation_ds:
      file_names: /data/val.jsonl
      global_batch_size: 128

  optim:
    name: fused_adam
    lr: 1e-5
    sched:
      name: CosineAnnealing
      warmup_steps: 1000
```

### NeMo 2.0 Equivalent Python Configuration

```python
from nemo.collections import llm
from nemo import lightning as nl
import nemo_run as run

# 1. Model configuration
model = llm.Llama3Config8B()

# 2. Data configuration
data = llm.SquadDataModule(
    train_path="/data/train.jsonl",
    validation_path="/data/val.jsonl",
    seq_length=4096,
    global_batch_size=128,
    micro_batch_size=1,
)

# 3. Strategy configuration
strategy = nl.MegatronStrategy(
    tensor_model_parallel_size=2,
    pipeline_model_parallel_size=1,
)

# 4. Trainer configuration
trainer = nl.Trainer(
    num_nodes=1,
    devices=8,
    accelerator="gpu",
    strategy=strategy,
    plugins=nl.MegatronMixedPrecision(precision="bf16-mixed"),
    max_steps=10000,
    log_every_n_steps=10,
    val_check_interval=500,
)

# 5. Optimizer configuration
optim = nl.MegatronOptimizerModule(
    config=nl.OptimizerConfig(
        optimizer="adam",
        lr=1e-5,
        bf16=True,
    ),
    lr_scheduler=nl.CosineAnnealingScheduler(
        warmup_steps=1000,
        max_steps=10000,
    ),
)

# 6. Compose recipe
recipe = llm.finetune_recipe(
    model=model,
    data=data,
    trainer=trainer,
    optim=optim,
    dir="/results/llama3_finetune",
    name="my_experiment",
)

# 7. Run training
run.run(recipe)
```

**Benefits of NeMo 2.0 approach:**
- Type checking and IDE support
- Easier to understand and modify
- Can add conditional logic
- Better error messages
- Programmatic control

---

## Migration Checklist

### For New Projects

✅ **Always use NeMo 2.0** - no migration needed!

### For Existing NeMo 1.x Projects

Follow this step-by-step migration:

#### Step 1: Analyze Current Configuration

```bash
# Identify all YAML config files
find . -name "*.yaml" -o -name "*.yml"

# Note the sections used:
# - trainer
# - exp_manager
# - model.data
# - model.optim
# - model (other parameters)
```

#### Step 2: Create Python Training Script

```python
# train.py
from nemo.collections import llm
from nemo import lightning as nl
import nemo_run as run

def main():
    # TODO: Convert YAML sections to Python
    pass

if __name__ == "__main__":
    main()
```

#### Step 3: Migrate Component by Component

**Convert in this order:**

1. **Model configuration**
   - Find model name and parameters
   - Use predefined config or create custom

2. **Data configuration**
   - Convert `model.data` → `DataModule`
   - Verify paths and parameters

3. **Strategy configuration**
   - Extract parallelism settings
   - Create `MegatronStrategy`

4. **Trainer configuration**
   - Convert `trainer` section
   - Add precision plugin

5. **Optimizer configuration**
   - Convert `model.optim`
   - Separate scheduler configuration

6. **Experiment management**
   - Convert `exp_manager`
   - Set up logger and callbacks

#### Step 4: Test Migration

```python
# Verify configuration
print("Model:", model)
print("Data:", data)
print("Trainer:", trainer)
print("Optimizer:", optim)

# Dry run (don't actually train)
# Check that all components initialize correctly
```

#### Step 5: Run Small-Scale Test

```python
# Test on small dataset
test_data = llm.SquadDataModule(
    train_path="/data/small_train.jsonl",
    validation_path="/data/small_val.jsonl",
    global_batch_size=8,
)

test_trainer = nl.Trainer(
    max_steps=100,          # Short test
    devices=1,              # Single GPU
)

# Run test
test_recipe = llm.finetune_recipe(
    model=model,
    data=test_data,
    trainer=test_trainer,
    optim=optim,
    dir="/tmp/test",
)

run.run(test_recipe)
```

#### Step 6: Full Migration

Once small-scale test succeeds:
- Use full dataset
- Full GPU configuration
- Full training steps
- Remove old YAML files

---

## Common Migration Issues and Solutions

### Issue 1: Precision Configuration

**Problem:**
```python
# This doesn't work in NeMo 2.0
trainer = nl.Trainer(precision="bf16")  # ❌
```

**Solution:**
```python
# Use MegatronMixedPrecision plugin
trainer = nl.Trainer(
    plugins=nl.MegatronMixedPrecision(precision="bf16-mixed")  # ✅
)
```

### Issue 2: Optimizer Names

**Problem:**
```python
# Old optimizer names don't work
optim_config = nl.OptimizerConfig(optimizer="fused_adam")  # ❌
```

**Solution:**
```python
# Use string names
optim_config = nl.OptimizerConfig(optimizer="adam")  # ✅
```

### Issue 3: Logger Configuration

**Problem:**
```python
# Logger not part of trainer in 2.0
trainer = nl.Trainer(
    logger={"name": "my_exp"}  # ❌
)
```

**Solution:**
```python
# Create separate logger
logger = NeMoLogger(name="my_exp", dir="/results")
trainer = nl.Trainer(logger=logger)  # ✅
```

### Issue 4: Data Path Parameters

**Problem:**
```python
# Old parameter names
data = llm.SquadDataModule(
    train_ds={"file_names": "/data/train.jsonl"}  # ❌
)
```

**Solution:**
```python
# New simplified parameters
data = llm.SquadDataModule(
    train_path="/data/train.jsonl"  # ✅
)
```

---

## NeMo Run: The New Standard

### What is NeMo Run?

**NeMo Run** is the new experiment orchestration library that makes NeMo 2.0 truly portable and reproducible.

**Documentation**: `https://docs.nvidia.com/nemo/run/latest/index.html`

### Key Features

1. **Multi-platform execution**
   - Local (single machine)
   - SLURM (HPC clusters)
   - Kubernetes (cloud)
   - Cloud platforms (AWS, GCP, Azure)

2. **Reproducible experiments**
   - Capture full configuration
   - Version control for experiments
   - Easy reproduction

3. **Simplified configuration**
   - Python-based recipes
   - Composable configurations
   - Easy sharing

### Using NeMo Run

```python
import nemo_run as run
from nemo.collections import llm

# Define experiment
@run.cli.factory
def llama3_finetune():
    return llm.llama3_8b.finetune_recipe(
        train_data_path="/data/train.jsonl",
        num_nodes=4,
        num_gpus_per_node=8,
    )

# Run locally
run.run(llama3_finetune)

# Or on SLURM
run.run(llama3_finetune, executor="slurm")

# Or on Kubernetes
run.run(llama3_finetune, executor="k8s")
```

---

## Best Practices for NeMo 2.0

### 1. Use Predefined Configs

```python
# Good: Use predefined configs
model = llm.Llama3Config8B()

# Instead of: Manual configuration
model = llm.GPTConfig(
    num_layers=32,
    hidden_size=4096,
    # ... many parameters
)
```

### 2. Leverage Type Checking

```python
# Enable type checking in your IDE
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from nemo import lightning as nl

# IDE will now provide autocomplete and type checking
trainer: nl.Trainer = nl.Trainer(...)
```

### 3. Use NeMo Run for Experiments

```python
# Good: Use NeMo Run
recipe = llm.finetune_recipe(...)
run.run(recipe)

# Instead of: Manual training
# trainer.fit(model, datamodule=data)
```

### 4. Version Control Your Configs

```python
# training_config.py
def get_training_config(version="v1"):
    if version == "v1":
        return {
            "lr": 1e-5,
            "batch_size": 128,
        }
    elif version == "v2":
        return {
            "lr": 5e-6,
            "batch_size": 256,
        }
```

### 5. Document Your Experiments

```python
def llama3_finetune_experiment():
    """
    Llama 3 8B fine-tuning experiment.

    Purpose: Fine-tune on domain-specific data
    Dataset: Medical conversations (50K samples)
    Expected duration: ~12 hours on 8x A100
    """
    return llm.llama3_8b.finetune_recipe(...)
```

---

## Comparison Table: NeMo 1.x vs 2.0

| Feature | NeMo 1.x | NeMo 2.0 |
|---------|----------|----------|
| **Configuration** | YAML files | Python code |
| **IDE Support** | Limited | Full (autocomplete, types) |
| **Flexibility** | Limited | High (programmatic) |
| **Experiment Management** | exp_manager | NeMo Run |
| **Trainer** | YAML section | nl.Trainer class |
| **Data** | YAML model.data | DataModule classes |
| **Optimizer** | YAML model.optim | OptimizerConfig |
| **Precision** | Simple flag | Plugin-based |
| **Extensibility** | Difficult | Easy (Python) |
| **Error Messages** | Generic | Type-checked |
| **Version Control** | YAML files | Python modules |
| **Testing** | Limited | Standard Python tests |

---

## Migration Support Resources

### Official Documentation

- **Migration Guide**: `https://docs.nvidia.com/nemo-framework/user-guide/latest/nemo-2.0/migration/index.html`
- **NeMo Run Docs**: `https://docs.nvidia.com/nemo/run/latest/index.html`
- **NeMo 2.0 API Reference**: `https://docs.nvidia.com/nemo-framework/user-guide/latest/nemotoolkit/index.html`

### Migration Guides by Component

- **Trainer**: `https://docs.nvidia.com/nemo-framework/user-guide/latest/nemo-2.0/migration/trainer.html`
- **Optimizer**: `https://docs.nvidia.com/nemo-framework/user-guide/latest/nemo-2.0/migration/optim.html`
- **Data**: Migration guide in official docs
- **Checkpointing**: Migration guide in official docs

### Community Support

- **GitHub Issues**: https://github.com/NVIDIA/NeMo/issues
- **Developer Forums**: https://forums.developer.nvidia.com/c/ai/nemo/
- **Example Recipes**: https://github.com/NVIDIA/NeMo/tree/main/scripts

---

## Quick Reference

### Essential Imports

```python
# Core imports for NeMo 2.0
from nemo.collections import llm
from nemo import lightning as nl
import nemo_run as run
from nemo.lightning.pytorch.callbacks import ModelCheckpoint
from nemo.lightning import NeMoLogger, AutoResume
```

### Minimal Working Example

```python
from nemo.collections import llm
import nemo_run as run

# Use predefined recipe
recipe = llm.llama3_8b.finetune_recipe(
    train_data_path="/data/train.jsonl",
    val_data_path="/data/val.jsonl",
    num_nodes=1,
    num_gpus_per_node=8,
    max_steps=10000,
    dir="/results/my_model",
)

# Run training
run.run(recipe)
```

---

## Summary

**NeMo 2.0 is the future of NeMo:**
- ✅ More flexible and powerful
- ✅ Better developer experience
- ✅ Easier to extend and customize
- ✅ Full IDE support
- ✅ Unified experiment management with NeMo Run

**For all new projects: Use NeMo 2.0**

**For existing projects: Migrate when possible**
- Better long-term maintainability
- Access to new features
- Improved debugging and testing
- Active development and support

---

For related topics, see:
- [📋 NeMo Best Practices](./nemo_best_practices.md)
- [🎯 Training Guide](./nemo_training.md)
- [🚀 Deployment Guide](./nemo_deployment.md)
- [📊 Data Preparation Guide](./nemo_data_preparation.md)
- [🎓 Post-Training Guide](./nemo_post_training.md)
