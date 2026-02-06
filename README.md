# AI Engineering Skills for Claude Code

A curated marketplace of Claude Code plugins for AI/ML engineering workflows.

## Available Plugins

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

### Jira Manager

Generate structured Jira tickets and integrate with Jira Server API for seamless issue management.

**Features:**
- Template-based ticket generation (Bug, Task, Story, Epic)
- Direct Jira Server API integration with Personal Access Token auth
- Full CRUD operations: create, search, read, update, comment, transition
- JQL search support with advanced filtering
- Per-directory configuration for multiple Jira servers/projects
- Interactive setup wizard for easy onboarding
- Support for Jira Wiki Markup formatting
- Status transitions and workflow management

[View Documentation](./jira-manager/README.md)

### Python Dev

Automatically runs [ruff](https://docs.astral.sh/ruff/) on Python files after every Write or Edit operation via `uvx`.

**What it does:**
- Fixes auto-fixable lint issues
- Sorts imports (isort-compatible)
- Formats code
- Reports remaining issues back to Claude

**Requirements:** `uv` installed and a Python project marker (`pyproject.toml`, `setup.py`, or `setup.cfg`) in the project root. Skips silently if either is missing.

## Installation

### Add Marketplace

```bash
/plugin marketplace add nikolaypavlov/claude-skills
```

### Install Plugins

```bash
# Install NeMo Builder
/plugin install nemo-builder@ai-engineering-skills

# Install Jira Manager
/plugin install jira-manager@ai-engineering-skills

# Install Python Dev (ruff linting, formatting, import sorting)
/plugin install python-dev@ai-engineering-skills
```

## Usage

Once installed, plugins are automatically available in Claude Code.

**NeMo Builder**: Start conversations about NeMo-related tasks (training, fine-tuning, deployment) and the skill will activate automatically.

**Jira Manager**: Ask to create, search, or update Jira tickets. The skill provides both text generation and direct API integration modes.

**Python Dev**: Runs automatically after every Write/Edit on `.py` files. No manual activation needed.

## Structure

```
claude-skills/
├── .claude-plugin/
│   └── marketplace.json          # Marketplace configuration
├── hooks/                        # Python Dev plugin
│   ├── hooks.json                # Hook configuration (PostToolUse)
│   └── ruff-lint.sh              # Ruff linting, formatting, import sorting
├── nemo-builder/                 # NeMo Builder plugin
│   ├── SKILL.md                  # Main skill file
│   ├── README.md                 # Documentation
│   ├── reference/                # Detailed guides
│   └── examples/                 # Code examples
├── jira-manager/                 # Jira Manager plugin
│   ├── SKILL.md                  # Main skill file
│   ├── README.md                 # Documentation
│   ├── pyproject.toml            # Python dependencies
│   ├── reference/                # Setup and config guides
│   ├── examples/                 # Ticket examples and code
│   └── tools/                    # API integration (Python)
└── README.md                     # This file
```
