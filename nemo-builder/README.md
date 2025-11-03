# NeMo Builder Skill

A comprehensive Claude Code skill for building AI solutions using NVIDIA NeMo 2.0 framework.

## Overview

This skill provides guidance for the complete AI development lifecycle with NeMo 2.0:
- **Data Preparation**: GPU-accelerated curation with NeMo Curator
- **Model Training**: Pre-training, fine-tuning, and PEFT (LoRA, P-tuning)
- **Post-Training**: RLHF with GRPO, DPO for alignment
- **Evaluation**: Comprehensive benchmarking with NeMo Eval
- **Deployment**: Production-ready inference with NIM, TensorRT-LLM, vLLM
- **Distributed Training**: Multi-GPU and multi-node scalability

## What is NeMo 2.0?

NVIDIA NeMo 2.0 is a scalable and cloud-native generative AI framework built for:
- **Large Language Models (LLMs)**: Llama, Mixtral, Gemma, Qwen, and more
- **Multimodal Models**: Vision-language and audio-visual models
- **Speech AI**: ASR, TTS, speaker recognition, and diarization

## Key Features

### Core Capabilities
- **GPU-Accelerated Data Curation**: Process billions of documents with NeMo Curator
- **Distributed Training**: Scale from single-GPU to 1000+ GPU clusters
- **Multiple Training Approaches**: Pre-training, SFT, LoRA, P-tuning
- **Post-Training & Alignment**: RLHF, DPO, GRPO for safety and helpfulness
- **HuggingFace Integration**: Seamless Day-0 support via NeMo AutoModel
- **Production Deployment**: Enterprise-ready inference with NIM
- **Comprehensive Evaluation**: Built-in benchmarks with NeMo Eval

### Supported NeMo Libraries
- **NeMo**: Core generative AI framework
- **NeMo Run**: Experiment management across platforms
- **NeMo Curator**: Data curation and quality filtering
- **NeMo AutoModel**: GPU-accelerated HuggingFace training
- **NeMo RL**: Post-training with RLHF, DPO, GRPO
- **NeMo Eval**: LLM evaluation and benchmarking
- **NeMo Export and Deploy**: Model export and serving
- **NeMo Megatron Bridge**: HF ↔ Megatron conversion

## Structure

```
nemo-builder/
├── SKILL.md                          # Main skill file with 7-phase workflow
├── README.md                         # This file
├── reference/                        # Detailed guides
│   ├── nemo_2.0_guide.md            # NeMo 2.0 overview and migration
│   ├── nemo_best_practices.md       # Universal best practices
│   ├── nemo_training.md             # Training workflows (SFT, PEFT)
│   ├── nemo_post_training.md        # RLHF, DPO, GRPO alignment
│   ├── nemo_deployment.md           # Production deployment
│   ├── nemo_data_preparation.md     # Data curation guide
│   └── nemo_speech_tools.md         # Speech AI tools guide
└── examples/                         # Code examples
    ├── finetune_llama.py            # Fine-tune Llama example
    ├── finetune_with_lora.py        # PEFT with LoRA
    ├── prepare_training_data.py     # Data preparation pipeline
    └── deploy_model.py              # Deployment workflows
```

## Quick Start

### 1. Installation

```bash
# Using NGC Container (Recommended)
docker pull nvcr.io/nvidia/nemo:24.01.framework
docker run --gpus all -it --rm nvcr.io/nvidia/nemo:24.01.framework

# Or install from PyPI
pip install nemo_toolkit[all]
```

### 2. Fine-tune a Model

```python
from nemo.collections import llm
import nemo_run as run

# Configure fine-tuning
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

### 3. Deploy with NIM

```bash
# Start NIM server
docker run -d \
    --gpus all \
    -p 8000:8000 \
    -v /models:/models \
    nvcr.io/nvidia/nim:24.01
```

## Skill Usage

When using this skill, Claude will guide you through 7 phases:

1. **Deep Research**: Understanding NeMo architecture and all libraries
2. **Environment Setup**: Installing and configuring NeMo
3. **Data Preparation**: Using NeMo Curator for GPU-accelerated curation
4. **Model Training**: Pre-training, SFT, or PEFT with distributed training
5. **Evaluation**: Comprehensive testing with NeMo Eval
6. **Post-Training** (Optional): RLHF/DPO alignment with NeMo RL
7. **Deployment**: Production deployment with NIM, TensorRT-LLM, or vLLM

## Reference Guides

The `reference/` directory contains comprehensive guides for each phase:

- [NeMo 2.0 Guide](./reference/nemo_2.0_guide.md) - Migration and key changes
- [NeMo Best Practices](./reference/nemo_best_practices.md) - Universal guidelines
- [Training Guide](./reference/nemo_training.md) - Complete training workflows
- [Data Preparation Guide](./reference/nemo_data_preparation.md) - Data curation
- [Post-Training Guide](./reference/nemo_post_training.md) - RLHF and alignment
- [Deployment Guide](./reference/nemo_deployment.md) - Production deployment
- [Speech AI Tools Guide](./reference/nemo_speech_tools.md) - Speech processing toolkit
- [Tutorials](./reference/nemo_tutorials.md) - Interactive Jupyter notebooks for hands-on learning

## Examples

See the [examples/](./examples/) directory for:
- Fine-tuning Llama models
- Training custom architectures
- Deploying with different backends
- Data preparation pipelines

## Resources

### Official Documentation
- **NeMo Framework**: https://docs.nvidia.com/nemo-framework/user-guide/latest/
- **NeMo Libraries Index**: https://docs.nvidia.com/nemo-framework/user-guide/latest/libraries/index.html
- **Speech AI Tools**: https://docs.nvidia.com/nemo-framework/user-guide/latest/nemotoolkit/tools/intro.html
- **All NeMo Libraries**:
  - [NeMo Toolkit](https://docs.nvidia.com/nemo-framework/user-guide/latest/nemotoolkit/index.html)
  - [NeMo Run](https://docs.nvidia.com/nemo/run/latest/index.html)
  - [NeMo Curator](https://docs.nvidia.com/nemo/curator/latest/index.html)
  - [NeMo AutoModel](https://docs.nvidia.com/nemo/automodel/latest/index.html)
  - [NeMo RL](https://docs.nvidia.com/nemo/rl/latest/index.html)
  - [NeMo Eval](https://docs.nvidia.com/nemo/evaluator/latest/index.html)
  - [NeMo Export and Deploy](https://docs.nvidia.com/nemo/export-deploy/latest/index.html)
  - [NeMo Megatron Bridge](https://docs.nvidia.com/nemo/megatron-bridge/latest/index.html)

### Community
- **GitHub Repository**: https://github.com/NVIDIA/NeMo
- **NGC Catalog**: https://catalog.ngc.nvidia.com/
- **Developer Forums**: https://forums.developer.nvidia.com/c/ai/nemo/
