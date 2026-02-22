# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

A curated marketplace of Claude Code plugins for AI/ML engineering workflows. Contains:

- **NeMo Builder** (`nemo-builder/`) -- NVIDIA NeMo 2.0 framework skill for AI development lifecycle (data prep, training, deployment). Documentation-only skill with reference guides and Python examples.
- **Jira Manager** (`jira-manager/`) -- Jira ticket generation and Server API integration. Hybrid skill with both text generation templates and Python API tools.
- **ACLI Manager** (`acli-manager/`) -- Atlassian CLI (acli) skill for managing Jira Cloud and Confluence Cloud from the command line. Documentation-only skill with command reference and workflow guides.
- **Python Dev** (`hooks/`) -- PreToolUse pre-commit hook: ruff (lint, format, import sort) + ty (type check) for Python, yamllint for YAML. Runs on staged files before `git commit`.

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

## Hooks

Hooks live in `hooks/` with config in `hooks/hooks.json`. The python-dev plugin uses a single PreToolUse hook on Bash that intercepts `git commit` commands:

- `hooks/pre-commit.sh` -- Reads `tool_input.command` from stdin JSON, matches `*git*commit*`, then for staged files: auto-fixes Python with ruff, runs final ruff lint + ty type check, validates YAML with yamllint. Blocks commit (exit 2) if issues remain.
- Pattern `*git*commit*` (not `*"git commit"*`) to match `git -C <path> commit` that Claude Code generates.

Each plugin with hooks must be registered separately in `marketplace.json` -- do not bundle unrelated hooks with skill-only plugins.

## Plugin Development

This repository is a Claude Code plugin. When creating or modifying skills, commands, hooks, agents, or plugin structure, prefer using skills from the `plugin-dev` plugin (e.g., `/skill-development`, `/plugin-structure`, `/hook-development`, `/agent-development`, `/command-development`).

## Conventions

- SKILL.md files use YAML frontmatter for skill metadata
- Python code uses full type annotations and tuple returns `(success: bool, message: str, data: Optional)`
- CLI tools communicate via JSON on stdin/stdout
- No automated test suite -- testing is done manually via example scripts in `examples/`
