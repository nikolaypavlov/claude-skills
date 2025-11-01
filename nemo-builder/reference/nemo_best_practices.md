# NeMo 2.0 Best Practices

This guide covers universal best practices for building AI solutions with NVIDIA NeMo 2.0, applicable across all project types (LLM, multimodal, speech AI).

---

## Project Structure and Organization

### Recommended Directory Structure

```
my-nemo-project/
├── configs/                 # Configuration files
│   ├── model/              # Model configs
│   ├── training/           # Training configs
│   └── data/               # Data configs
├── data/                   # Raw and processed data
│   ├── raw/
│   ├── processed/
│   └── splits/
├── scripts/                # Training and evaluation scripts
│   ├── train.py
│   ├── evaluate.py
│   └── preprocess.py
├── checkpoints/            # Model checkpoints
├── logs/                   # Training logs and metrics
├── results/                # Evaluation results
├── notebooks/              # Jupyter notebooks for analysis
├── requirements.txt        # Python dependencies
└── README.md               # Project documentation
```

### Configuration Management

**Use YAML configs for reproducibility:**
```yaml
# config.yaml example
model:
  name: llama3_8b
  precision: bf16

training:
  max_steps: 10000
  val_check_interval: 500
  gradient_clip_val: 1.0

optimizer:
  name: adam
  lr: 1e-5
  weight_decay: 0.01
```

**Version control your configs:**
- Track all configuration files in git
- Tag configs with experiment IDs
- Document config changes in commit messages

---

## Experiment Tracking and Reproducibility

### Use NeMo Run for Consistency

**Benefits of NeMo Run:**
- Portable configs across environments (local, SLURM, K8s, cloud)
- Automatic experiment tracking
- Easy reproduction of experiments
- Built-in checkpoint management

**Example NeMo Run usage:**
```python
import nemo_run as run

# Define experiment
@run.cli.factory
def experiment_config():
    return {
        "model": "llama3_8b",
        "data": "/data/my_dataset",
        "batch_size": 128,
    }

# Run experiment
run.run(experiment_config)
```

### Experiment Logging

**Track these metrics:**
- Loss (training and validation)
- Learning rate schedule
- Gradient norms
- GPU memory usage
- Throughput (tokens/sec, samples/sec)
- Wall-clock time per step

**Use TensorBoard for visualization:**
```python
from lightning.pytorch.loggers import TensorBoardLogger

logger = TensorBoardLogger("logs/", name="my_experiment")
trainer = nl.Trainer(logger=logger)
```

### Reproducibility Checklist

- [ ] All configs saved and versioned
- [ ] Random seeds set and documented
- [ ] Environment specifications recorded (CUDA version, NeMo version)
- [ ] Data processing pipeline documented
- [ ] Model initialization strategy documented
- [ ] Hardware configuration recorded (GPU type, count)

---

## Distributed Training Best Practices

### Parallelism Strategy Selection

**Data Parallelism (DP):**
- Use when: Model fits on single GPU
- Best for: Small to medium models
- Simple to implement and debug

**Tensor Parallelism (TP):**
- Use when: Model doesn't fit on single GPU
- Splits model layers across GPUs
- Low communication overhead within node
- Recommended: Keep TP within single node (8 GPUs max)

**Pipeline Parallelism (PP):**
- Use when: Model is very large
- Splits model layers vertically
- Good for cross-node scaling
- Trade-off: Pipeline bubbles reduce efficiency

**Sequence Parallelism (SP):**
- Use with: Long sequences
- Reduces memory for activations
- Combine with TP for maximum efficiency

**Recommended combinations:**
```python
# Small model (< 7B params), single node
strategy = nl.MegatronStrategy(
    tensor_model_parallel_size=1,
    pipeline_model_parallel_size=1,
)

# Medium model (7-13B params), multi-GPU
strategy = nl.MegatronStrategy(
    tensor_model_parallel_size=4,
    pipeline_model_parallel_size=1,
)

# Large model (70B+ params), multi-node
strategy = nl.MegatronStrategy(
    tensor_model_parallel_size=8,
    pipeline_model_parallel_size=4,
)
```

### GPU Memory Management

**Strategies to reduce memory:**
1. **Gradient checkpointing**: Trade compute for memory
2. **Mixed precision**: Use BF16 or FP16 instead of FP32
3. **Optimizer state sharding**: Distribute optimizer states
4. **Activation checkpointing**: Recompute instead of storing
5. **Sequence parallelism**: Split long sequences

**Monitor memory usage:**
```bash
# During training, monitor GPU memory
nvidia-smi -l 1

# Or programmatically
import torch
print(f"Allocated: {torch.cuda.memory_allocated() / 1e9:.2f} GB")
print(f"Cached: {torch.cuda.memory_reserved() / 1e9:.2f} GB")
```

### Communication Optimization

**Minimize cross-node communication:**
- Keep TP within nodes
- Use PP for cross-node parallelism
- Enable NCCL optimizations

**NCCL environment variables:**
```bash
export NCCL_DEBUG=INFO
export NCCL_IB_DISABLE=0  # Enable InfiniBand
export NCCL_NET_GDR_LEVEL=5  # GPU Direct RDMA
```

---

## Checkpoint Management

### Checkpoint Saving Strategy

**Frequency considerations:**
- **Too frequent**: Wastes I/O bandwidth and storage
- **Too infrequent**: Risk of losing progress
- **Recommendation**: Every 500-1000 steps, or every 1-2 hours

**Configure checkpoint saving:**
```python
from lightning.pytorch.callbacks import ModelCheckpoint

checkpoint_callback = ModelCheckpoint(
    dirpath="/checkpoints/my_model",
    filename="model-{epoch:02d}-{val_loss:.2f}",
    save_top_k=3,  # Keep top 3 checkpoints
    monitor="val_loss",
    mode="min",
    every_n_train_steps=500,
)
```

### Checkpoint Format

**NeMo uses two checkpoint types:**

1. **PyTorch Lightning checkpoints (.ckpt)**
   - Contains full training state
   - Includes optimizer state, scheduler state
   - Use for resuming training

2. **NeMo checkpoints (.nemo)**
   - Self-contained model package
   - Includes model weights and config
   - Use for inference and deployment

**Convert between formats:**
```python
# .ckpt → .nemo
from nemo.collections.nlp.models import MegatronGPTModel

model = MegatronGPTModel.load_from_checkpoint("/path/to/model.ckpt")
model.save_to("/path/to/model.nemo")
```

### Checkpoint Storage

**Best practices:**
- Use fast storage (NVMe, parallel file systems)
- Implement checkpoint sharding for large models
- Set up automatic backup to object storage (S3, GCS)
- Clean up old checkpoints regularly

---

## Performance Optimization Strategies

### Data Loading Optimization

**Bottleneck: Data loading can limit GPU utilization**

**Strategies:**
1. **Use sufficient dataloader workers:**
   ```python
   dataloader = DataLoader(
       dataset,
       batch_size=32,
       num_workers=4,  # Tune based on CPU cores
       pin_memory=True,  # Faster CPU→GPU transfer
       persistent_workers=True,  # Keep workers alive
   )
   ```

2. **Pre-process and cache data:**
   - Tokenize and cache datasets before training
   - Use memory-mapped files for large datasets
   - Store processed data in fast storage

3. **Use packed sequences:**
   - Combine multiple short sequences into one
   - Reduces padding overhead
   - Increases GPU utilization

### Mixed Precision Training

**Use BF16 for better stability:**
```python
trainer = nl.Trainer(
    precision="bf16-mixed",  # Recommended for A100/H100
    # or "16-mixed" for older GPUs
)
```

**Benefits:**
- 2x faster training
- 2x less memory usage
- Minimal accuracy impact

**FP8 training (H100 GPUs):**
- Even faster than BF16
- Requires recipe tuning for convergence
- Supported in NeMo 2.0

### Gradient Accumulation

**For large effective batch sizes:**
```python
trainer = nl.Trainer(
    accumulate_grad_batches=4,  # Effective batch = 4x larger
)
```

**When to use:**
- Cannot fit desired batch size in memory
- Want to maintain batch size semantics while scaling
- Trade-off: Slower updates, more stable training

### Profiling and Debugging

**Profile training performance:**
```python
from lightning.pytorch.profilers import PyTorchProfiler

profiler = PyTorchProfiler(
    dirpath="./profiler_logs",
    filename="profile",
)
trainer = nl.Trainer(profiler=profiler)
```

**Identify bottlenecks:**
- Data loading time vs compute time
- GPU utilization percentage
- Memory usage patterns
- Communication overhead

---

## Security and Compliance Considerations

### Data Privacy

**For training with sensitive data:**
- Implement data anonymization/pseudonymization
- Use secure enclaves for data processing
- Encrypt data at rest and in transit
- Audit data access and usage

### Model Security

**Protect model weights:**
- Encrypt checkpoints
- Implement access controls
- Use secure storage (vault services)
- Audit checkpoint access

### PII and Safety

**Use NeMo Curator for PII removal:**
```python
from nemo_curator.filters import PIIFilter

pii_filter = PIIFilter(
    remove_email=True,
    remove_phone=True,
    remove_ssn=True,
)
cleaned_data = pii_filter.filter(raw_data)
```

**Content safety:**
- Filter toxic, harmful, or biased content
- Implement safety classifiers
- Human review of edge cases

### Compliance

**For regulated industries:**
- Document data provenance
- Implement model versioning and tracking
- Maintain audit logs
- Ensure reproducibility for compliance

---

## Common Pitfalls and How to Avoid Them

### Pitfall 1: Not Monitoring Training Early

**Problem:** Training runs for hours/days before issues detected

**Solution:**
- Validate immediately after first few steps
- Monitor loss curve from the start
- Set up alerting for anomalies (loss spikes, NaN)

### Pitfall 2: Incorrect Data Formatting

**Problem:** Model trains but performs poorly due to data issues

**Solution:**
- Validate data format before training
- Inspect preprocessed samples manually
- Check tokenization is correct
- Verify label distributions

### Pitfall 3: Suboptimal Parallelism Configuration

**Problem:** Poor GPU utilization, slow training

**Solution:**
- Start with recommended configs for model size
- Profile and measure throughput
- Iterate on parallelism settings
- Use NeMo Auto Configurator (if available)

### Pitfall 4: Running Out of Disk Space

**Problem:** Training stops due to full disk (checkpoints, logs)

**Solution:**
- Monitor disk usage actively
- Set up automatic cleanup policies
- Use checkpoint rotation (keep only N recent)
- Stream logs to external storage

### Pitfall 5: Not Using Version Control

**Problem:** Cannot reproduce past experiments

**Solution:**
- Git track all code and configs
- Tag experiments with git commit hash
- Document environment versions
- Use NeMo Run for portable configs

---

## Development Workflow Recommendations

### Iterative Development Cycle

1. **Start Small**
   - Prototype on tiny dataset (100 samples)
   - Use single GPU
   - Verify pipeline works end-to-end

2. **Validate on Medium Scale**
   - Scale to 10% of full dataset
   - Use multi-GPU (1 node)
   - Tune hyperparameters

3. **Full-Scale Training**
   - Use complete dataset
   - Scale to multi-node if needed
   - Run for full training duration

4. **Evaluate and Iterate**
   - Comprehensive evaluation on test set
   - Error analysis
   - Refine based on results

### Debugging Tips

**Training diverges (loss → NaN):**
- Reduce learning rate
- Increase gradient clipping
- Check for data issues (inf, NaN values)
- Try more stable optimizer (AdamW)

**Training is slow:**
- Profile to find bottleneck
- Check GPU utilization (should be >80%)
- Optimize data loading
- Tune parallelism strategy

**Out of memory:**
- Reduce batch size
- Enable gradient checkpointing
- Use mixed precision (BF16)
- Increase tensor parallelism

**Model not learning:**
- Verify data preprocessing is correct
- Check learning rate (too low or too high)
- Inspect model outputs manually
- Try different initialization

---

## Resource Estimation

### GPU Requirements by Model Size

| Model Size | Min GPUs | Recommended GPUs | GPU Memory | Training Time (100B tokens) |
|-----------|----------|------------------|------------|----------------------------|
| 1B params | 1x A100 | 4x A100 | 40GB | ~1 week |
| 7B params | 4x A100 | 8x A100 | 80GB | ~2 weeks |
| 13B params | 8x A100 | 16x A100 | 80GB | ~3 weeks |
| 70B params | 32x A100 | 64x A100 | 80GB | ~1 month |

*Estimates assume A100 80GB GPUs with optimal parallelism*

### Storage Requirements

**Checkpoints:**
- Model size ≈ params × 2 bytes (BF16)
- Full checkpoint ≈ params × 6 bytes (model + optimizer state)
- Keep 3-5 checkpoints: 15-30x model size

**Data:**
- Raw data: Original size
- Processed data: 1.5-2x raw size (after tokenization)
- Allow 3x raw data size for working space

**Logs:**
- ~1MB per 1000 steps
- TensorBoard logs: ~100MB per full run

---

## Quick Reference

### Essential Commands

```bash
# Check NeMo version
python -c "import nemo; print(nemo.__version__)"

# List available models
python -c "from nemo.collections import llm; print(llm.list_models())"

# Launch training with NeMo Run
nemo run train.py --config config.yaml

# Convert checkpoint formats
python scripts/convert_checkpoint.py --input model.ckpt --output model.nemo

# Evaluate model
python scripts/evaluate.py --checkpoint model.nemo --data test_data.jsonl
```

### Configuration Templates

**Small-scale prototyping:**
```python
# Single GPU, small model
trainer = nl.Trainer(
    max_steps=1000,
    val_check_interval=100,
    devices=1,
    precision="bf16-mixed",
)
```

**Production training:**
```python
# Multi-node, large model
trainer = nl.Trainer(
    max_steps=100000,
    val_check_interval=1000,
    num_nodes=4,
    devices=8,
    precision="bf16-mixed",
    strategy=nl.MegatronStrategy(
        tensor_model_parallel_size=8,
        pipeline_model_parallel_size=2,
    ),
)
```

---

## Additional Resources

### Official Documentation

- **NeMo Framework Overview**: `https://docs.nvidia.com/nemo-framework/user-guide/latest/overview.html`
- **NeMo Toolkit**: `https://docs.nvidia.com/nemo-framework/user-guide/latest/nemotoolkit/index.html`
- **NeMo Libraries Index**: `https://docs.nvidia.com/nemo-framework/user-guide/latest/libraries/index.html`

### NeMo Libraries

- **NeMo Run**: `https://docs.nvidia.com/nemo/run/latest/index.html`
- **NeMo Curator**: `https://docs.nvidia.com/nemo/curator/latest/index.html`
- **NeMo AutoModel**: `https://docs.nvidia.com/nemo/automodel/latest/index.html`
- **NeMo RL**: `https://docs.nvidia.com/nemo/rl/latest/index.html`
- **NeMo Eval**: `https://docs.nvidia.com/nemo/evaluator/latest/index.html`
- **NeMo Export and Deploy**: `https://docs.nvidia.com/nemo/export-deploy/latest/index.html`
- **NeMo Megatron Bridge**: `https://docs.nvidia.com/nemo/megatron-bridge/latest/index.html`

### Community Resources

- **GitHub Repository**: https://github.com/NVIDIA/NeMo
- **NGC Catalog**: https://catalog.ngc.nvidia.com/
- **Developer Forums**: https://forums.developer.nvidia.com/c/ai/nemo/
- **Training Recipes**: https://github.com/NVIDIA/NeMo/tree/main/scripts

---

For phase-specific best practices, refer to:
- [🎯 Training Guide](./nemo_training.md)
- [🚀 Deployment Guide](./nemo_deployment.md)
- [📊 Data Preparation Guide](./nemo_data_preparation.md)
