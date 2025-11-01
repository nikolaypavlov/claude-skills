---
name: nemo-builder
description: Guide for building AI solutions using NVIDIA NeMo 2.0 framework. Use when developing LLMs, multimodal models, or speech AI applications - from data preparation and training to deployment.
---

# NVIDIA NeMo 2.0 Development Guide

## Overview

To create high-quality AI solutions using NVIDIA NeMo 2.0 framework, use this skill. NeMo 2.0 is a scalable and cloud-native generative AI framework built for researchers and developers working on Large Language Models, Multimodal, and Speech AI. This skill guides you through the entire development lifecycle - from data curation to production deployment.

**Key Capabilities:**
- Pre-training and fine-tuning LLMs (Llama 3, Mixtral, Gemma, etc.)
- Building multimodal and vision-language models
- Developing speech AI applications (ASR, TTS, speaker recognition)
- Speech data tools (Forced Aligner, Data Explorer, CTC-Segmentation)
- Scalable training from single-GPU to multi-node clusters
- Production deployment via NIM and TensorRT-LLM

---

# Process

## 🚀 High-Level Workflow

Creating a production-ready AI solution with NeMo 2.0 involves seven main phases:

### Phase 1: Deep Research and Planning

#### 1.1 Understand NeMo 2.0 Architecture

Before diving into implementation, understand the core components and design principles:

**NeMo 2.0 Core Components and Libraries:**

**Core Framework:**
- **NeMo**: Generative AI framework for PyTorch-based model design and implementation
  - Docs: `https://docs.nvidia.com/nemo-framework/user-guide/latest/nemotoolkit/index.html`
- **NeMo Run**: Streamlines configuration, execution, and management of ML experiments
  - Docs: `https://docs.nvidia.com/nemo/run/latest/index.html`
- **Megatron Core**: Advanced parallelism strategies for distributed training
- **Lightning**: Distributed training orchestration

**Data and Preparation:**
- **NeMo Curator**: GPU-accelerated data curation for extracting high-quality text from web corpora
  - Docs: `https://docs.nvidia.com/nemo/curator/latest/index.html`

**Training and Fine-Tuning:**
- **NeMo AutoModel**: GPU-accelerated training for Hugging Face models with Day-0 support
  - Docs: `https://docs.nvidia.com/nemo/automodel/latest/index.html`
- **NeMo Megatron Bridge**: Bidirectional conversion between Hugging Face and Megatron models
  - Docs: `https://docs.nvidia.com/nemo/megatron-bridge/latest/index.html`

**Post-Training (RLHF):**
- **NeMo RL**: Reinforcement learning library supporting RLHF, DPO, GRPO for alignment
  - Docs: `https://docs.nvidia.com/nemo/rl/latest/index.html`

**Evaluation and Deployment:**
- **NeMo Eval**: Comprehensive evaluation module for large language models
  - Docs: `https://docs.nvidia.com/nemo/evaluator/latest/index.html`
- **NeMo Export and Deploy**: Tools for exporting to TensorRT-LLM, vLLM via Triton Inference Server
  - Docs: `https://docs.nvidia.com/nemo/export-deploy/latest/index.html`

**Development Philosophy:**
- **Modularity**: Components can be used independently or together
- **Scalability**: Design for growth from prototype to production
- **Reproducibility**: Use standardized recipes and checkpoints
- **Cloud-Native**: Support for on-premises, datacenter, and cloud deployment

#### 1.2 Study NeMo Framework Documentation

**Fetch the latest NeMo documentation:**

Use WebFetch to load: `https://docs.nvidia.com/nemo-framework/user-guide/latest/overview.html`

This document contains the complete NeMo 2.0 framework overview and architecture.

**Important: This skill uses NeMo 2.0**

NeMo 2.0 represents a fundamental shift from YAML-based to Python-based configuration. If you're familiar with NeMo 1.x or see YAML-based examples elsewhere, review the migration guide:

- [📘 NeMo 2.0 Guide](./reference/nemo_2.0_guide.md) - Complete guide to NeMo 2.0
- **Migration Documentation**: `https://docs.nvidia.com/nemo-framework/user-guide/latest/nemo-2.0/migration/index.html`

**Key differences in NeMo 2.0:**
- Python-based configuration (no YAML files)
- NeMo Run for experiment management
- Type-safe configurations with IDE support
- Explicit component composition

#### 1.3 Load Reference Materials

**Essential reference files (load as needed):**

- [📋 NeMo Best Practices](./reference/nemo_best_practices.md) - Universal guidelines
- [🎯 Training Guide](./reference/nemo_training.md) - Training and fine-tuning
- [📊 Data Preparation](./reference/nemo_data_preparation.md) - Data curation with NeMo Curator
- [🎓 Post-Training](./reference/nemo_post_training.md) - RLHF alignment (optional)
- [🚀 Deployment Guide](./reference/nemo_deployment.md) - Production deployment
- [🎤 Speech Tools](./reference/nemo_speech_tools.md) - Speech AI toolkit (if needed)

#### 1.4 Define Project Requirements

Clearly define your project scope:

**Model Type:**
- LLM (pre-training, supervised fine-tuning, PEFT)
- Multimodal (vision-language, audio-visual)
- Speech AI (ASR, TTS, speaker recognition)

**Scale Requirements:**
- Training infrastructure (single-GPU, multi-GPU, multi-node)
- Model size and parameter count
- Dataset size and complexity
- Deployment target (cloud, on-premises, edge)

**Performance Goals:**
- Accuracy/quality metrics
- Training time constraints
- Inference latency requirements
- Throughput needs

#### 1.5 Create a Comprehensive Implementation Plan

Based on your research, create a detailed plan that includes:

**Environment Setup:**
- NVIDIA GPU requirements and availability
- Container setup (NeMo container vs custom environment)
- Compute orchestration (SLURM, Kubernetes, cloud)
- Storage requirements for datasets and checkpoints

**Data Pipeline:**
- Data sources and collection strategy
- Curation and cleaning approach (NeMo Curator)
- Data format and preprocessing requirements
- Dataset size and splits (train/val/test)

**Model Configuration:**
- Base model selection (from NeMo catalog or Hugging Face)
- Training approach (pre-training, SFT, PEFT/LoRA)
- Parallelism strategy (data, tensor, pipeline, sequence parallelism)
- Hyperparameters (learning rate, batch size, optimizer)

**Evaluation Strategy:**
- Evaluation metrics and benchmarks
- Validation frequency during training
- Testing on held-out datasets
- Performance baselines to beat

**Deployment Plan:**
- Inference framework (NIM, TensorRT-LLM, vLLM)
- Optimization techniques (quantization, FP8)
- Serving infrastructure and scalability
- Monitoring and observability

---

### Phase 2: Environment Setup

#### 2.1 Prepare Compute Infrastructure

**Verify GPU availability:**
```bash
nvidia-smi
```

**Install NeMo Framework:**

Option A - Using NGC Container (Recommended):
```bash
docker pull nvcr.io/nvidia/nemo:24.01.framework
docker run --gpus all -it --rm -v $(pwd):/workspace nvcr.io/nvidia/nemo:24.01.framework
```

Option B - Install from Source:
```bash
pip install nemo_toolkit[all]
```

#### 2.2 Configure Development Environment

**Set up NeMo Run for experiment management:**
- Configure for your compute environment (local, SLURM, Kubernetes)
- Set up experiment tracking and logging
- Configure checkpoint storage location

**Verify installation:**
```bash
python -c "import nemo; print(nemo.__version__)"
```

---

### Phase 3: Data Preparation

#### 3.1 Collect and Organize Data

**Gather training data:**
- Identify data sources (web scraping, existing datasets, synthetic)
- Download and organize raw data
- Document data provenance and licensing

#### 3.2 Use NeMo Curator for Data Curation

**Load the data preparation guide:**
[📊 Data Preparation Guide](./reference/nemo_data_preparation.md)

**Key steps:**
- Quality filtering (remove low-quality, duplicate content)
- Deduplication (exact and fuzzy matching)
- PII removal and safety filtering
- Data format conversion
- Synthetic data generation (if needed)

#### 3.3 Create Dataset Splits

**Split data appropriately:**
- Training set (typically 80-90%)
- Validation set (typically 5-10%)
- Test set (typically 5-10%)
- Ensure stratification for balanced evaluation

---

### Phase 4: Model Development

#### 4.1 Select Base Model or Architecture

**Choose your starting point:**

**Pre-trained Models (Transfer Learning):**
- Browse NeMo model catalog
- Check Hugging Face for compatible models
- Consider model size vs available compute
- Verify license compatibility

**Training from Scratch:**
- Define model architecture
- Set model dimensions (hidden size, layers, attention heads)
- Configure parallelism strategy for scale

#### 4.2 Configure Training

**Load the training guide:**
[🎯 Training Guide](./reference/nemo_training.md)

**Configure NeMo Run experiment:**
```python
# Example structure
from nemo.collections import llm

# Configure model
model_config = llm.Llama3Config8B()

# Configure training strategy
strategy = nl.MegatronStrategy(
    tensor_model_parallel_size=2,
    pipeline_model_parallel_size=2,
)

# Configure training recipe
recipe = llm.llama3_8b.finetune_recipe(
    dir="/path/to/checkpoints",
    num_nodes=4,
    num_gpus_per_node=8,
)
```

**Key configuration areas:**
- Model architecture and size
- Parallelism strategy (TP, PP, DP)
- Optimizer and learning rate schedule
- Batch size and gradient accumulation
- Mixed precision training (FP16, BF16, FP8)
- Checkpoint saving frequency

#### 4.3 Run Training

**Launch training:**
```bash
# Using NeMo Run
nemo run train.py

# Monitor training progress
tensorboard --logdir /path/to/logs
```

**Monitor during training:**
- Loss curves (training and validation)
- Learning rate schedule
- GPU utilization and memory
- Throughput (samples/sec, tokens/sec)
- Checkpoint creation

#### 4.4 Implement PEFT (Optional)

**For parameter-efficient fine-tuning:**
- LoRA (Low-Rank Adaptation)
- P-tuning
- Adapter modules

Benefits: Lower compute requirements, faster training, easier deployment

---

### Phase 5: Evaluation and Testing

#### 5.1 Define Evaluation Metrics

**Choose appropriate metrics:**

**LLMs:**
- Perplexity on validation set
- Benchmark scores (MMLU, HellaSwag, etc.)
- Human evaluation for quality
- Task-specific metrics

**Speech AI:**
- Word Error Rate (WER) for ASR
- Mean Opinion Score (MOS) for TTS
- Speaker identification accuracy

**Multimodal:**
- Visual Question Answering accuracy
- Image captioning quality (BLEU, CIDEr)
- Cross-modal retrieval metrics

#### 5.2 Run Comprehensive Evaluation

**Evaluate on test sets:**
- Never seen during training
- Representative of production distribution
- Cover edge cases and challenging examples

**Benchmark against baselines:**
- Compare to base model (pre-fine-tuning)
- Compare to state-of-the-art models
- Measure improvement over previous versions

#### 5.3 Analyze Results and Iterate

**Review evaluation results:**
- Identify strengths and weaknesses
- Find failure modes and error patterns
- Determine if goals are met

**Iterate if needed:**
- Adjust hyperparameters
- Collect additional data for weak areas
- Try different training strategies
- Consider architecture modifications

---

### Phase 6: Post-Training and Alignment (Optional)

For models requiring alignment with human preferences, use NeMo RL for post-training:

#### 6.1 Understand Post-Training Methods

**Load the post-training guide:**
[🎓 Post-Training Guide](./reference/nemo_post_training.md)

**Available methods:**
- **RLHF with GRPO**: Group Relative Policy Optimization for reinforcement learning
- **DPO**: Direct Preference Optimization without reward modeling
- **Supervised Fine-Tuning**: Instruction tuning on curated datasets
- **Reward Model Training**: Training preference-based reward models

**When to use post-training:**
- Improving helpfulness and harmlessness
- Aligning with human preferences
- Reducing hallucinations
- Task-specific optimization (code, math, reasoning)

#### 6.2 Prepare Preference Data

**Data requirements:**
- Preference pairs (chosen vs rejected responses)
- High-quality prompts
- Diverse scenarios
- Consistent annotation guidelines

**Data sources:**
- Human feedback collection
- AI feedback (constitutional AI)
- Existing datasets (HelpSteer, Anthropic HH)
- Synthetic preference generation

#### 6.3 Configure and Run Post-Training

**Using NeMo RL:**
```python
# Load documentation
# Docs: https://docs.nvidia.com/nemo/rl/latest/index.html

# Configure GRPO training
from nemo_rl import GRPO

grpo_config = GRPO(
    base_model="/models/sft_model.nemo",
    preference_data="/data/preferences.jsonl",
    algorithm="grpo",
)

# Run training
grpo_config.train()
```

**Monitor alignment metrics:**
- Reward model scores
- Win rates vs baseline
- Human evaluation scores
- Safety benchmarks

#### 6.4 Evaluate Aligned Model

**Compare to base model:**
- Helpfulness improvements
- Safety improvements
- Task performance
- Behavioral changes

**Use NeMo Eval for comprehensive evaluation:**
- Docs: `https://docs.nvidia.com/nemo/evaluator/latest/index.html`

---

### Phase 7: Deployment

#### 7.1 Export Model for Inference

**Prepare model for deployment:**

**Load the deployment guide:**
[🚀 Deployment Guide](./reference/nemo_deployment.md)

**Export options:**
- NeMo checkpoint → NIM (enterprise deployment)
- NeMo checkpoint → TensorRT-LLM (optimized inference)
- NeMo checkpoint → vLLM (alternative inference engine)

**Use NeMo Export and Deploy:**
- Docs: `https://docs.nvidia.com/nemo/export-deploy/latest/index.html`

#### 7.2 Optimize for Production

**Apply optimization techniques:**
- Quantization (INT8, FP8)
- TensorRT optimization
- KV cache optimization
- Batch size tuning for throughput

#### 7.3 Deploy to Production

**Choose deployment strategy:**

**NVIDIA NIM (Recommended for Enterprise):**
- Containerized microservice
- TensorRT-LLM optimized
- Production-ready APIs
- Scalable and secure

**TensorRT-LLM:**
- Maximum performance
- Custom deployment scenarios
- Fine-grained control

**vLLM:**
- Open-source alternative
- PagedAttention for efficiency
- Good for research and prototypes

#### 7.4 Monitor and Maintain

**Set up monitoring:**
- Request latency and throughput
- GPU utilization and memory
- Error rates and exceptions
- Model quality metrics (sampling outputs)

**Plan for updates:**
- Model versioning strategy
- A/B testing new models
- Rollback procedures
- Continuous evaluation

---

# Code Examples

For complete code examples, see the [examples/](./examples/) directory:

- **finetune_llama.py** - Fine-tune Llama 3 8B
- **finetune_with_lora.py** - PEFT with LoRA
- **prepare_training_data.py** - Data preparation pipeline
- **deploy_model.py** - Deployment workflows

---

For detailed implementation guidance, always refer to the phase-specific reference files (see Phase 1, section 1.3) and official NVIDIA NeMo documentation.
