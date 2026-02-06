# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

A curated marketplace of Claude Code skills for AI/ML engineering workflows. Contains two independent skills:

- **NeMo Builder** (`nemo-builder/`) -- NVIDIA NeMo 2.0 framework skill for AI development lifecycle (data prep, training, deployment). Documentation-only skill with reference guides and Python examples.
- **Jira Manager** (`jira-manager/`) -- Jira ticket generation and Server API integration. Hybrid skill with both text generation templates and Python API tools.

## Skill Architecture

Each skill follows the same structure:
- `SKILL.md` -- Main entry point that Claude reads when the skill activates
- `reference/` -- Detailed guides loaded on-demand (referenced from SKILL.md)
- `examples/` -- Code examples and sample outputs

The marketplace is configured in `.claude-plugin/marketplace.json`.

## Jira Manager Development

The only skill with executable code. Python package in `jira-manager/`.

**Dependencies:** Python >=3.10, `jira>=3.10.0`

**Package management:** Uses `uv`. Install with:
```bash
cd jira-manager && uv pip install -e .
```

**Run tools directly:**
```bash
uv run jira-manager/tools/create_ticket.py
uv run jira-manager/tools/update_ticket.py
```

**Key files:**
- `tools/jira_client.py` -- Core JiraManager class with full CRUD operations
- `tools/create_ticket.py` -- CLI entry point for ticket creation (reads JSON from stdin)
- `tools/update_ticket.py` -- CLI entry point for search/update operations

**Configuration:** Environment variables `JIRA_SERVER_URL` and `JIRA_API_KEY` (Personal Access Token).

## Plugin Development

This repository is a Claude Code plugin. When creating or modifying skills, commands, hooks, agents, or plugin structure, prefer using skills from the `plugin-dev` plugin (e.g., `/skill-development`, `/plugin-structure`, `/hook-development`, `/agent-development`, `/command-development`).

## Conventions

- SKILL.md files use YAML frontmatter for skill metadata
- Python code uses full type annotations and tuple returns `(success: bool, message: str, data: Optional)`
- CLI tools communicate via JSON on stdin/stdout
- No automated test suite -- testing is done manually via example scripts in `examples/`
