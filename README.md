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

PreToolUse pre-commit hook that lints all staged files before `git commit` via `uvx`.

**Python files** (ruff + ty):
- Auto-fixes lint issues, sorts imports, formats code with ruff
- Type checks with ty (Astral's Rust-based type checker)
- Re-stages auto-fixed files automatically

**YAML files** (yamllint):
- Validates YAML syntax and style (max line length: 120)

**Requirements:** `uv` installed. Skips silently if prerequisites are not met.

### ACLI Manager

Atlassian CLI (acli) skill for managing Jira Cloud and Confluence Cloud from the command line.

**Features:**
- Work items, projects, boards, sprints management
- Confluence spaces and pages
- Bulk operations and automation workflows
- ADF format support for rich content

### PR Reviewer

PR/MR code review with GitHub and GitLab support (including self-hosted).

**Features:**
- Auto-detects platform from git remotes (`gh` / `glab`)
- 7 specialized review agents: code quality, test coverage, error handling, comment accuracy, type design, code simplification
- Fetches existing PR/MR discussion and Jira/Linear issue context
- Validates all findings: enforces file:line references, deduplicates, filters weak results, removes by-design items
- Posts inline comments or single top-level comment with user permission

### Autoresearch

Autonomous hyperparameter and model optimization with parallel GPU researchers using Agent Teams.

**Features:**
- YAML-based experiment configuration
- Parallel GPU researchers in isolated git worktrees
- Coordinated experiment loop with metrics tracking
- Cross-researcher learning broadcasts
- Automatic cleanup of worktrees and resources

Run `/autoresearch:autoresearch [path-to-autoresearch.yaml]` to start optimization.

### PDF Design System

Skill + command for converting markdown to PDF using a canonical editorial design (navy/gold/cream, Fraunces + Source Serif 4 + JetBrains Mono).

**Features:**
- Canonical stylesheet maintained inside the skill; no per-project setup required by default
- pandoc + WeasyPrint pipeline with explicit invocation documented in the skill
- `/pdf-design-system:init` scaffolds `docs/pdf-overrides.css` for per-project wordmark and palette tokens (opt-in)
- Strict CSS scope: project overrides may only redeclare `:root` tokens

### iCloud MCP

Local Rust MCP server for Apple iCloud Calendar (CalDAV) and Mail (IMAP), shipping prebuilt binaries via GitHub Releases.

**Features:**
- 10 tools: calendar list/list-events/get/search/create, mail list-folders/search/get-message/create-draft, and `auth_status` diagnostic
- Read + create only by design: events can be created, mail can only be saved as drafts (no SMTP)
- Connection-pooled IMAP session with NOOP-based health check across tool calls
- macOS Keychain credential fallback; explicit timeouts on every network call; structured `URL_ELICITATION_REQUIRED` (-32042) error when unconfigured
- 4-target prebuilt binaries (darwin arm64/x64, linux x64/arm64); no Rust toolchain required for plugin users
- `/icloud-mcp:setup` interactive wizard for first-time credential capture

**Requirements:** Apple ID with two-factor authentication enabled (needed to mint app-specific passwords).

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

# Install Python Dev (pre-commit: ruff + ty + yamllint)
/plugin install python-dev@ai-engineering-skills

# Install ACLI Manager
/plugin install acli-manager@ai-engineering-skills

# Install PR Reviewer
/plugin install pr-reviewer@ai-engineering-skills

# Install Autoresearch
/plugin install autoresearch@ai-engineering-skills

# Install PDF Design System
/plugin install pdf-design-system@ai-engineering-skills

# Install iCloud MCP (prebuilt binary auto-fetched on first session)
/plugin install icloud-mcp@ai-engineering-skills
```

## Usage

Once installed, plugins are automatically available in Claude Code.

**NeMo Builder**: Start conversations about NeMo-related tasks (training, fine-tuning, deployment) and the skill will activate automatically.

**Jira Manager**: Ask to create, search, or update Jira tickets. The skill provides both text generation and direct API integration modes.

**Python Dev**: Runs automatically before `git commit` on staged `.py` and `.yaml`/`.yml` files. Blocks commit if issues remain after auto-fix.

**ACLI Manager**: Start conversations about Jira Cloud or Confluence Cloud tasks and the skill will activate automatically.

**PR Reviewer**: Run `/pr-reviewer:review-pr` to review the current branch's PR/MR. Supports `gh` (GitHub) and `glab` (GitLab, including self-hosted).

**Autoresearch**: Run `/autoresearch:autoresearch` with an `autoresearch.yaml` config in your project root to launch parallel GPU optimization.

**PDF Design System**: Ask Claude Code to convert a markdown document to PDF and the skill activates automatically. Run `/pdf-design-system:init` once per project if you want a custom wordmark or palette tokens.

**iCloud MCP**: After install run `/icloud-mcp:setup` to capture your Apple ID and an app-specific password (stored in macOS Keychain or `.envrc` on Linux). Then ask "list my iCloud calendars", "search mail from <someone>", or "draft an email to <someone> about <topic>".

## Structure

```
claude-skills/
├── .claude-plugin/
│   └── marketplace.json          # Marketplace configuration
├── hooks/                        # Python Dev plugin
│   ├── hooks.json                # Hook configuration (PreToolUse)
│   └── pre-commit.sh             # Pre-commit: ruff + ty + yamllint
├── nemo-builder/                 # NeMo Builder plugin
│   ├── SKILL.md                  # Main skill file
│   ├── references/               # Detailed guides
│   └── examples/                 # Code examples
├── jira-manager/                 # Jira Manager plugin
│   ├── SKILL.md                  # Main skill file
│   ├── pyproject.toml            # Python dependencies
│   ├── references/               # Setup and config guides
│   ├── examples/                 # Ticket examples and code
│   └── tools/                    # API integration (Python)
├── acli-manager/                 # ACLI Manager plugin
│   ├── SKILL.md                  # Main skill file
│   └── references/               # Workflow and ADF guides
├── pr-reviewer/                  # PR Reviewer plugin
│   ├── commands/
│   │   └── review-pr.md          # Orchestrator command
│   └── agents/                   # 7 specialized review agents
├── autoresearch/                 # Autoresearch plugin
│   ├── commands/
│   │   └── autoresearch.md       # Entry point command
│   ├── skills/autoresearch/
│   │   ├── SKILL.md              # Lead agent coordination
│   │   ├── references/           # Config schema, learnings format
│   │   └── scripts/              # Worktree setup, harvest, cleanup
│   └── agents/
│       └── researcher.md         # GPU researcher agent
├── pdf-design-system/            # PDF Design System plugin
│   ├── SKILL.md                  # Canonical stylesheet + pandoc/WeasyPrint flow
│   ├── assets/                   # Fonts, baseline CSS
│   ├── commands/
│   │   └── init.md               # /pdf-design-system:init scaffolder
│   ├── references/               # Override schema, design rationale
│   └── examples/                 # Sample documents
├── icloud-mcp/                   # iCloud MCP plugin (Rust binary)
│   ├── Cargo.toml                # rmcp + libdav + async-imap deps
│   ├── src/                      # main.rs, caldav.rs, imap_client.rs, config.rs, error.rs
│   ├── scripts/
│   │   ├── launch.sh             # Wrapper: ensures binary then exec
│   │   └── install-binary.sh     # Downloads release tarball or cargo fallback
│   ├── hooks/
│   │   └── hooks.json            # SessionStart hook -> install-binary.sh
│   ├── commands/
│   │   └── setup.md              # /icloud-mcp:setup interactive wizard
│   ├── tests/                    # CalDAV integration tests via httpmock
│   └── .mcp.json                 # MCP server registration (-> launch.sh)
└── README.md                     # This file
```

## Release infrastructure

`.github/workflows/release-icloud-mcp.yml` builds prebuilt icloud-mcp binaries for 4 targets (darwin arm64/x64, linux x64/arm64) on every `icloud-mcp-v*` tag push. All third-party actions are pinned to commit SHAs; Dependabot (`.github/dependabot.yml`) keeps them current via weekly PRs.
