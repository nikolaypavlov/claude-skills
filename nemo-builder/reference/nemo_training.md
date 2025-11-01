# NeMo 2.0 Training Guide

This comprehensive guide covers training workflows in NeMo 2.0, from configuration to execution, for LLMs, multimodal models, and speech AI.

---

## Training Overview

### Training Approaches in NeMo 2.0

**1. Pre-training from Scratch**
- Training a model from random initialization
- Requires large datasets (100B+ tokens)
- Computationally expensive
- Full control over model behavior

**2. Supervised Fine-Tuning (SFT)**
- Start from pre-trained checkpoint
- Train on task-specific data
- Much faster than pre-training
- Most common approach

**3. Parameter-Efficient Fine-Tuning (PEFT)**
- Only train small subset of parameters
- Methods: LoRA, P-tuning, adapters
- Fast training, low compute
- Easy to deploy multiple variants

---

## Phase 1: Model Selection and Configuration

### Selecting a Base Model

**Option A: Use Pre-trained Model from Catalog**

```python
from nemo.collections import llm

# Browse available models
available_models = llm.list_models()
print(available_models)

# Common models:
# - Llama 3 (8B, 70B)
# - Mixtral (8x7B, 8x22B)
# - Gemma (2B, 7B)
# - Qwen (7B, 14B, 72B)
```

**Option B: Import from Hugging Face**

```python
from nemo.collections.nlp.models import MegatronGPTModel

# Convert HuggingFace model to NeMo
model = MegatronGPTModel.from_pretrained(
    "meta-llama/Llama-2-7b-hf",
    save_path="/models/llama-2-7b.nemo"
)
```

**Option C: Define Custom Architecture**

```python
from nemo.collections import llm

# Define custom model config
model_config = llm.GPTConfig(
    num_layers=32,
    hidden_size=4096,
    num_attention_heads=32,
    ffn_hidden_size=11008,
    vocab_size=32000,
)
```

### Model Configuration Parameters

**Critical parameters to configure:**

```python
model_config = llm.Llama3Config8B(
    # Architecture
    num_layers=32,                    # Number of transformer layers
    hidden_size=4096,                 # Hidden dimension size
    num_attention_heads=32,           # Number of attention heads
    ffn_hidden_size=14336,           # Feed-forward network size

    # Context and vocabulary
    seq_length=4096,                  # Maximum sequence length
    vocab_size=128256,                # Vocabulary size

    # Efficiency
    bf16=True,                        # Use BF16 precision
    params_dtype=torch.bfloat16,     # Parameter data type

    # Regularization
    attention_dropout=0.0,            # Attention dropout rate
    hidden_dropout=0.0,               # Hidden layer dropout
    layernorm_epsilon=1e-5,          # Layer norm epsilon
)
```

---

## Phase 2: Data Configuration

### Dataset Formats

**JSON Lines (Recommended for LLMs):**
```jsonl
{"input": "Question: What is NeMo?", "output": "NeMo is an AI framework by NVIDIA."}
{"input": "Question: What is PyTorch?", "output": "PyTorch is a machine learning library."}
```

**Packed Sequences (For Efficiency):**
```python
from nemo.collections.nlp.data import GPTSFTPackedDataset

dataset = GPTSFTPackedDataset(
    data_path="/data/train.jsonl",
    tokenizer=tokenizer,
    max_seq_length=4096,
    pack_sequences=True,  # Combine multiple samples
)
```

### DataModule Configuration

```python
from nemo.collections import llm

# Configure data module
data_module = llm.SquadDataModule(
    # Paths
    train_path="/data/train.jsonl",
    validation_path="/data/val.jsonl",
    test_path="/data/test.jsonl",

    # Tokenization
    tokenizer="meta-llama/Llama-2-7b-hf",
    seq_length=4096,

    # Batching
    micro_batch_size=1,               # Per-GPU batch size
    global_batch_size=128,            # Total batch size across all GPUs

    # Loading
    num_workers=4,                    # DataLoader workers
    pin_memory=True,                  # Faster GPU transfer
)
```

### Custom Data Pipeline

```python
from torch.utils.data import Dataset, DataLoader
import json

class CustomDataset(Dataset):
    def __init__(self, data_path, tokenizer, max_length=4096):
        self.tokenizer = tokenizer
        self.max_length = max_length

        # Load data
        with open(data_path, 'r') as f:
            self.data = [json.loads(line) for line in f]

    def __len__(self):
        return len(self.data)

    def __getitem__(self, idx):
        item = self.data[idx]

        # Format prompt
        prompt = f"Question: {item['input']}\nAnswer: {item['output']}"

        # Tokenize
        tokens = self.tokenizer(
            prompt,
            max_length=self.max_length,
            truncation=True,
            padding="max_length",
            return_tensors="pt"
        )

        return {
            "input_ids": tokens["input_ids"].squeeze(),
            "attention_mask": tokens["attention_mask"].squeeze(),
            "labels": tokens["input_ids"].squeeze(),
        }
```

---

## Phase 3: Training Strategy Configuration

### Parallelism Strategy

**Select based on model size and hardware:**

```python
from nemo.lightning import MegatronStrategy

# Small models (1-7B params), single node
strategy = MegatronStrategy(
    tensor_model_parallel_size=1,      # No tensor parallelism
    pipeline_model_parallel_size=1,    # No pipeline parallelism
    virtual_pipeline_model_parallel_size=None,
    context_parallel_size=1,
    sequence_parallel=False,
)

# Medium models (7-13B params), single node
strategy = MegatronStrategy(
    tensor_model_parallel_size=4,      # Split across 4 GPUs
    pipeline_model_parallel_size=1,
    sequence_parallel=True,            # Enable sequence parallelism
)

# Large models (70B+ params), multi-node
strategy = MegatronStrategy(
    tensor_model_parallel_size=8,      # 8-way tensor parallel (within node)
    pipeline_model_parallel_size=4,    # 4-way pipeline parallel (across nodes)
    virtual_pipeline_model_parallel_size=2,  # Interleaved pipeline
    sequence_parallel=True,
)
```

### Optimizer Configuration

```python
from nemo.core.config import OptimizerConfig

optimizer = OptimizerConfig(
    # Optimizer type
    name="adam",                       # or "sgd", "adamw"

    # Learning rate
    lr=1e-5,                          # Initial learning rate

    # Adam parameters
    betas=(0.9, 0.999),               # Beta coefficients
    eps=1e-8,                         # Epsilon for numerical stability
    weight_decay=0.01,                # L2 regularization

    # Gradient clipping
    clip_grad=1.0,                    # Max gradient norm
)
```

### Learning Rate Scheduler

```python
from nemo.core.config import SchedulerConfig

scheduler = SchedulerConfig(
    # Scheduler type
    name="CosineAnnealing",           # or "WarmupHoldDecay", "InverseSquareRootAnnealing"

    # Warmup
    warmup_steps=1000,                # Linear warmup steps

    # Cosine decay
    max_steps=10000,                  # Total training steps
    min_lr=1e-6,                      # Minimum learning rate
)
```

---

## Phase 4: Training Execution

### Complete Training Recipe

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

# 3. Training strategy
strategy = nl.MegatronStrategy(
    tensor_model_parallel_size=2,
    pipeline_model_parallel_size=1,
)

# 4. Trainer configuration
trainer = nl.Trainer(
    # Compute
    devices=8,                        # GPUs per node
    num_nodes=1,                      # Number of nodes
    accelerator="gpu",

    # Training duration
    max_steps=10000,

    # Validation
    val_check_interval=500,
    limit_val_batches=50,

    # Logging
    log_every_n_steps=10,

    # Checkpointing
    enable_checkpointing=True,

    # Precision
    precision="bf16-mixed",

    # Strategy
    strategy=strategy,
)

# 5. Optimizer and scheduler
optim = nl.MegatronOptimizerModule(
    config=nl.OptimizerConfig(
        optimizer="adam",
        lr=1e-5,
        weight_decay=0.01,
        bf16=True,
    ),
    lr_scheduler=nl.CosineAnnealingScheduler(
        warmup_steps=1000,
        max_steps=10000,
    ),
)

# 6. Recipe composition
recipe = llm.finetune_recipe(
    model=model,
    data=data,
    trainer=trainer,
    optim=optim,
    dir="/results/my_finetuned_model",
    name="llama3_8b_finetune",
)

# 7. Execute training
run.run(recipe)
```

### Simplified Training (Using Pre-defined Recipe)

```python
from nemo.collections import llm
import nemo_run as run

# Use pre-defined recipe
recipe = llm.llama3_8b.finetune_recipe(
    # Data
    train_data_path="/data/train.jsonl",
    val_data_path="/data/val.jsonl",

    # Compute
    num_nodes=1,
    num_gpus_per_node=8,

    # Output
    dir="/results/llama3_finetune",

    # Training params
    max_steps=10000,
    val_check_interval=500,
)

# Run training
run.run(recipe)
```

### Monitor Training Progress

**TensorBoard:**
```bash
tensorboard --logdir /results/my_finetuned_model/logs
```

**Key metrics to monitor:**
- **Loss curves**: Should decrease smoothly
- **Learning rate**: Follows schedule correctly
- **Gradient norm**: Should be stable, spikes indicate issues
- **Throughput**: Samples/sec or tokens/sec
- **GPU utilization**: Should be >80%
- **Memory usage**: Should be stable

---

## Phase 5: Advanced Training Techniques

### Parameter-Efficient Fine-Tuning (PEFT)

#### LoRA (Low-Rank Adaptation)

```python
from nemo.collections.nlp.parts.peft_config import LoraConfig

# Configure LoRA
lora_config = LoraConfig(
    target_modules=["attention.query_key_value"],  # Modules to apply LoRA
    adapter_dim=32,                                 # LoRA rank
    alpha=32,                                       # Scaling factor
    dropout=0.1,                                    # LoRA dropout
)

# Apply LoRA to model
model.add_adapter(lora_config)

# Only LoRA parameters are trained
model.freeze()  # Freeze base model
model.unfreeze_adapter()  # Unfreeze LoRA layers
```

**Benefits of LoRA:**
- 10-100x fewer trainable parameters
- Faster training
- Less memory usage
- Multiple adapters can coexist

#### P-Tuning

```python
from nemo.collections.nlp.parts.peft_config import PtuningConfig

ptuning_config = PtuningConfig(
    num_virtual_tokens=10,             # Number of virtual prompt tokens
    encoder_hidden=1024,               # Hidden size of prompt encoder
)

model.add_adapter(ptuning_config)
```

### Mixed Precision Training

**BF16 Training (Recommended):**
```python
trainer = nl.Trainer(
    precision="bf16-mixed",            # Mixed BF16/FP32
)
```

**FP8 Training (H100 GPUs):**
```python
from nemo.lightning.pytorch.strategies import FP8Strategy

strategy = FP8Strategy(
    tensor_model_parallel_size=2,
    fp8_recipe={
        "amax_history_len": 1024,
        "amax_compute_algo": "most_recent",
    }
)

trainer = nl.Trainer(
    precision="fp8",
    strategy=strategy,
)
```

### Curriculum Learning

```python
# Start with shorter sequences, gradually increase
curriculum_schedule = {
    0: 512,        # Steps 0-2000: 512 seq length
    2000: 1024,    # Steps 2000-5000: 1024 seq length
    5000: 2048,    # Steps 5000-8000: 2048 seq length
    8000: 4096,    # Steps 8000+: 4096 seq length
}

# Implement in training loop
def update_seq_length(step):
    for threshold, seq_len in sorted(curriculum_schedule.items()):
        if step >= threshold:
            current_seq_len = seq_len
    return current_seq_len
```

### Gradient Accumulation

```python
trainer = nl.Trainer(
    accumulate_grad_batches=8,         # Accumulate 8 batches
    # Effective batch size = micro_batch_size * accumulate_grad_batches * num_gpus
)
```

---

## Phase 6: Resume Training from Checkpoint

### Resume from NeMo Checkpoint

```python
# Resume training
recipe = llm.llama3_8b.finetune_recipe(
    # ... other params ...
    resume_from_checkpoint="/checkpoints/model-step=5000.ckpt",
)

run.run(recipe)
```

### Continue Training with Different Config

```python
# Load existing checkpoint
model = llm.Llama3Model.restore_from("/checkpoints/model.nemo")

# Continue with new config
new_recipe = llm.finetune_recipe(
    model=model,
    # ... new training params ...
    max_steps=15000,  # Train for 5000 more steps
)
```

---

## Training Recipes for Common Scenarios

### Scenario 1: Quick Fine-Tune on Small Dataset

```python
# Single GPU, small dataset (<10K samples)
recipe = llm.llama3_8b.finetune_recipe(
    train_data_path="/data/small_train.jsonl",
    val_data_path="/data/small_val.jsonl",
    num_nodes=1,
    num_gpus_per_node=1,
    max_steps=1000,
    micro_batch_size=4,
    global_batch_size=4,
    lr=5e-5,
    dir="/results/quick_finetune",
)
```

### Scenario 2: Production Fine-Tune

```python
# Multi-GPU, large dataset (>100K samples)
recipe = llm.llama3_70b.finetune_recipe(
    train_data_path="/data/large_train.jsonl",
    val_data_path="/data/large_val.jsonl",
    num_nodes=4,
    num_gpus_per_node=8,
    max_steps=50000,
    micro_batch_size=1,
    global_batch_size=512,
    lr=1e-5,
    val_check_interval=1000,
    dir="/results/production_finetune",
)
```

### Scenario 3: PEFT with LoRA

```python
from nemo.collections.nlp.parts.peft_config import LoraConfig

# Configure LoRA
lora_config = LoraConfig(
    target_modules=["attention.query_key_value", "attention.dense"],
    adapter_dim=64,
    alpha=64,
)

# Fine-tune with LoRA
recipe = llm.llama3_8b.lora_finetune_recipe(
    train_data_path="/data/train.jsonl",
    peft_config=lora_config,
    num_nodes=1,
    num_gpus_per_node=4,
    max_steps=5000,
    dir="/results/lora_finetune",
)
```

---

## Troubleshooting Training Issues

### Issue: Loss is NaN or Infinite

**Causes:**
- Learning rate too high
- Gradient explosion
- Numerical instability
- Bad data (inf/nan values)

**Solutions:**
```python
# 1. Reduce learning rate
optimizer.lr = 1e-6  # Start very low

# 2. Increase gradient clipping
optimizer.clip_grad = 0.5  # Lower clip threshold

# 3. Check data
# Inspect samples for inf/nan
for batch in dataloader:
    assert not torch.isnan(batch["input_ids"]).any()
    assert not torch.isinf(batch["input_ids"]).any()

# 4. Use more stable precision
trainer.precision = "bf16-mixed"  # Better than fp16
```

### Issue: Training is Very Slow

**Diagnose:**
```python
# Profile training
from lightning.pytorch.profilers import PyTorchProfiler

profiler = PyTorchProfiler(
    dirpath="./profiler_logs",
    filename="training_profile",
)
trainer = nl.Trainer(profiler=profiler)
```

**Common causes and fixes:**

1. **Data loading bottleneck:**
   ```python
   # Increase workers
   data_module.num_workers = 8

   # Enable pinned memory
   data_module.pin_memory = True
   ```

2. **Suboptimal parallelism:**
   ```python
   # Experiment with TP/PP ratios
   # Aim for high GPU utilization
   nvidia-smi -l 1  # Monitor utilization
   ```

3. **Frequent validation:**
   ```python
   # Reduce validation frequency
   trainer.val_check_interval = 1000  # Instead of 100
   ```

### Issue: Out of Memory

**Solutions (in order of preference):**

1. **Reduce batch size:**
   ```python
   micro_batch_size = 1  # Minimum
   ```

2. **Enable gradient checkpointing:**
   ```python
   model.gradient_checkpointing = True
   ```

3. **Use sequence parallelism:**
   ```python
   strategy.sequence_parallel = True
   ```

4. **Increase tensor parallelism:**
   ```python
   strategy.tensor_model_parallel_size = 4  # Split across more GPUs
   ```

5. **Use CPU offloading (last resort):**
   ```python
   from nemo.collections.nlp.modules.common.megatron.megatron_init import initialize_model_parallel_for_nemo

   initialize_model_parallel_for_nemo(
       cpu_offload=True,  # Offload to CPU RAM
   )
   ```

### Issue: Model Not Learning

**Checks:**
1. **Verify data is correct:**
   ```python
   # Print sample inputs/outputs
   for batch in dataloader:
       print(tokenizer.decode(batch["input_ids"][0]))
       break
   ```

2. **Check learning rate:**
   ```python
   # Learning rate might be too low
   # Try increasing by 10x
   optimizer.lr = 1e-4  # If was 1e-5
   ```

3. **Verify loss calculation:**
   ```python
   # Ensure labels are properly set
   # Check loss is computed on correct tokens
   ```

4. **Check model is trainable:**
   ```python
   # Verify parameters have gradients
   for name, param in model.named_parameters():
       if param.requires_grad:
           print(f"{name}: {param.grad is not None}")
   ```

---

## Best Practices Summary

1. **Start small**: Prototype on subset before full training
2. **Monitor actively**: Watch loss, LR, throughput from beginning
3. **Validate early**: Run validation after first 100 steps
4. **Checkpoint frequently**: Every 500-1000 steps
5. **Log everything**: Track all hyperparameters and metrics
6. **Version control**: Git track configs and code
7. **Document experiments**: Record what worked and what didn't
8. **Profile before scaling**: Optimize on small scale first

---

## Additional Resources

### NeMo Documentation

- **NeMo Toolkit**: `https://docs.nvidia.com/nemo-framework/user-guide/latest/nemotoolkit/index.html`
- **NeMo Run**: `https://docs.nvidia.com/nemo/run/latest/index.html`
- **NeMo AutoModel** (for HuggingFace models): `https://docs.nvidia.com/nemo/automodel/latest/index.html`
- **NeMo Megatron Bridge**: `https://docs.nvidia.com/nemo/megatron-bridge/latest/index.html`

### Training Resources

- **NeMo Training Recipes**: https://github.com/NVIDIA/NeMo/tree/main/scripts
- **Training at Scale Guide**: https://docs.nvidia.com/nemo-framework/user-guide/latest/nemotoolkit/nlp/nemo_megatron/intro.html

### Research Papers

- **Megatron-LM**: https://arxiv.org/abs/1909.08053
- **LoRA**: https://arxiv.org/abs/2106.09685
- **Flash Attention**: https://arxiv.org/abs/2205.14135

---

For related topics, see:
- [📋 NeMo Best Practices](./nemo_best_practices.md)
- [📊 Data Preparation Guide](./nemo_data_preparation.md)
- [🚀 Deployment Guide](./nemo_deployment.md)
