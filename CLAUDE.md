# CLAUDE.md

## Project Overview

A curated marketplace of Claude Code plugins for AI/ML engineering workflows. Contains:

- **NeMo Builder** (`nemo-builder/`) -- NVIDIA NeMo 2.0 framework skill for AI development lifecycle (data prep, training, deployment). Documentation-only skill with reference guides and Python examples.
- **Jira Manager** (`jira-manager/`) -- Jira ticket generation and Server API integration. Hybrid skill with both text generation templates and Python API tools.
- **ACLI Manager** (`acli-manager/`) -- Atlassian CLI (acli) skill for managing Jira Cloud and Confluence Cloud from the command line. Documentation-only skill with command reference and workflow guides.
- **Python Dev** (`hooks/`) -- PreToolUse pre-commit hook: ruff (lint, format, import sort) + ty (type check) for Python, yamllint for YAML. Runs on staged files before `git commit`.
- **PR Reviewer** (`pr-reviewer/`) -- PR/MR code review with GitHub and GitLab support (including self-hosted). Command (`review-pr`) + 7 agents. Fetches existing discussion and Jira/Linear context, validates findings with file:line enforcement, posts inline or single comments with user permission.
- **Autoresearch** (`autoresearch/`) -- Autonomous hyperparameter/model optimization with parallel GPU researchers using Agent Teams. Command (`autoresearch`) + lead skill + researcher agent. Coordinates worktree-isolated experiments across multiple GPUs, tracks metrics, broadcasts learnings.
- **PDF Design System** (`pdf-design-system/`) -- Skill + command for converting markdown to PDF using a canonical editorial design (navy/gold/cream, Fraunces + Source Serif 4 + JetBrains Mono). Default path uses only the skill's canonical stylesheet. Per-project customization (wordmark, palette) is opt-in via `/pdf-design-system:init`, which scaffolds `docs/pdf-overrides.css` with `:root` token redeclarations only.
- **iCloud MCP** (`icloud-mcp/`) -- Local Rust MCP server for Apple iCloud Calendar (CalDAV via `libdav`) and Mail (IMAP via `async-imap` + `tokio-rustls`). Read + create-only: events can be created; mail can only be saved as drafts via IMAP APPEND (no SMTP). Credentials via `APPLE_ID`/`APPLE_APP_PASSWORD` env vars with macOS Keychain fallback.

## Plugin Architecture

Most plugins use skills with the same structure:
- `SKILL.md` -- Main entry point that Claude reads when the skill activates
- `references/` -- Detailed guides loaded on-demand (referenced from SKILL.md)
- `examples/` -- Code examples and sample outputs

PR Reviewer uses a different pattern - command + agents:
- `commands/review-pr.md` -- Orchestrator command invoked via `/pr-reviewer:review-pr`
- `agents/` -- 7 specialized review agents launched by the command

Autoresearch uses command + skill + agent:
- `commands/autoresearch.md` -- Entry point invoked via `/autoresearch:autoresearch`, parses YAML config and validates environment
- `skills/autoresearch/SKILL.md` -- Lead agent coordination program (worktree creation, researcher spawning, experiment loop)
- `agents/researcher.md` -- GPU researcher agent that runs experiments in isolated worktrees
- `skills/autoresearch/scripts/` -- Shell/Python utilities (worktree-setup.sh, harvest.py, cleanup.sh)

The marketplace is configured in `.claude-plugin/marketplace.json`.

## iCloud MCP Development

Rust binary plugin. Not a skill - it ships as a standalone MCP server registered via `icloud-mcp/.mcp.json`.

**Build:**
```bash
cd icloud-mcp && cargo build --release
```

The binary lands at `icloud-mcp/target/release/icloud-mcp`. `.mcp.json` references it via `${CLAUDE_PLUGIN_ROOT}/target/release/icloud-mcp`.

**Key files:**
- `src/main.rs` -- entry point, `IcloudServer` struct with `#[tool_router]`, 9 tools, stdio transport
- `src/caldav.rs` -- thin wrapper around `libdav::CalDavClient` (list_calendars, list_events, get_event, search_events, create_event)
- `src/imap_client.rs` -- `async-imap` over `tokio-rustls` (list_folders, search, get_message, create_draft via APPEND)
- `src/config.rs` -- env-or-Keychain credential loading
- `src/error.rs` -- McpError helpers

**Configuration:** Environment variables `APPLE_ID` and `APPLE_APP_PASSWORD` (a 16-char app-specific password from account.apple.com). On macOS, password can also live in Keychain under service `icloud-mcp`, account `$APPLE_ID`.

**Design constraint:** No SMTP. Drafts are APPENDed to the IMAP Drafts folder with the `\Draft` flag; the user reviews and sends them manually in iCloud Mail. This keeps the server from producing external side-effects.

## Jira Manager Development

The only skill with executable code. Python package in `jira-manager/`.

**Dependencies:** Python >=3.10, `jira>=3.10.0`

**Package management:** Uses `uv`. Install with:
```bash
cd jira-manager && uv sync
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

## Release Workflow

- Always bump plugin version in `.claude-plugin/marketplace.json` before pushing changes that affect a plugin (hooks, skills, etc.)

## Conventions

- SKILL.md files use YAML frontmatter for skill metadata
- Python code uses full type annotations and tuple returns `(success: bool, message: str, data: Optional)`
- CLI tools communicate via JSON on stdin/stdout
- No automated test suite -- testing is done manually via example scripts in `examples/`

### Rust projects

Every Rust crate in this repo must use `cargo fmt` (rustfmt) and `cargo clippy` and pass both before commit:

```bash
cargo fmt --check
cargo clippy --all-targets
```

Rules:
- Each Rust crate has a `rustfmt.toml` (or inherits sensible defaults) and pins lint policy in `Cargo.toml` under `[lints]` -- at minimum `unsafe_code = "forbid"` under `[lints.rust]` and `clippy::all = warn` (with `priority = -1`) under `[lints.clippy]`.
- Fix clippy warnings rather than suppressing them. Use `#[allow(...)]` only with a comment explaining why.
- Run `cargo fmt` after any code change. Do not hand-format -- let rustfmt own layout.
- `cargo build --release` must succeed warning-free before pushing.
