# AI Engineering Skills for Claude Code

A curated marketplace of Claude Code skills for AI/ML engineering workflows.

## Available Skills

### NeMo Builder

Comprehensive skill for building AI solutions using NVIDIA NeMo 2.0 framework.

**Features:**
- Complete AI development lifecycle (data preparation → training → deployment)
- Support for all 8 NeMo libraries (Core, Run, Curator, AutoModel, RL, Eval, Export/Deploy, Megatron Bridge)
- Pre-training, fine-tuning, and PEFT (LoRA, P-tuning)
- Post-training with RLHF (GRPO, DPO)
- Production deployment with NIM, TensorRT-LLM, vLLM
- Speech AI tools (Forced Aligner, Data Explorer, CTC-Segmentation)
- Distributed training across multi-GPU and multi-node clusters

[View Documentation](./nemo-builder/README.md)

## Installation

### Add Marketplace

```bash
/plugin marketplace add nikolaypavlov/claude-skills
```

### Install Skills

```bash
/plugin install nemo-builder@ai-engineering-skills
```

## Usage

Once installed, skills are automatically available in Claude Code. For NeMo Builder, simply start a conversation about NeMo-related tasks and the skill will activate.

## Structure

```
claude-skills/
├── .claude-plugin/
│   └── marketplace.json          # Marketplace configuration
├── nemo-builder/                 # NeMo 2.0 Builder skill
│   ├── SKILL.md                  # Main skill file
│   ├── plugin.json               # Plugin metadata
│   ├── README.md                 # Documentation
│   ├── reference/                # Detailed guides
│   └── examples/                 # Code examples
└── README.md                     # This file
```

## Contributing

This marketplace is curated for high-quality AI/ML engineering skills. Contributions and suggestions are welcome.

## License

Individual skills may have their own licenses. See each skill's directory for details.
