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

### Monobank MCP

Local Rust MCP server + CLI that pulls Monobank Personal API statements into the shared `~/finances/data.db` SQLite store. Ingest plugin in the personal-finance family - owns `mono_*` tables, standalone, no umbrella required for ingest.

**Features:**
- 3 MCP tools: `ensure_synced` (inline incremental sync bounded by `max_wait_seconds`, default 90s), `get_sync_status`, `list_mono_accounts`
- CLI: `init`, `accounts`, `backfill --from <date>`, `sync`, `serve`, `--probe`
- Per-chunk atomic SQLite transaction (INSERT OR IGNORE on `mono_transactions` + UPSERT on `mono_sync_state` in one commit) - a kill mid-chunk never leaves the cursor ahead of the data
- Auto-seed sync state for newly-discovered accounts; freshness skip on repeat syncs within the configured window (default 300s)
- Token resolution: `MONOBANK_TOKEN` env var primary, OS keychain fallback via `keyring` crate
- 4-target prebuilt binaries (darwin arm64/x64, linux x64/arm64); cargo fallback if no prebuilt matches the host
- `/monobank-mcp:setup` interactive wizard with `--probe` JSON diagnostic (non-zero exit on auth failure)

**Requirements:** Personal Monobank account with the mobile app installed (used to scan the token QR at <https://api.monobank.ua/> - see [Getting a Personal API token](./monobank-mcp/README.md#getting-a-personal-api-token)).

### Privat24 Skill

Python Claude Code skill that imports Privat24 web-cabinet statement exports (XLSX) into the shared `~/finances/data.db` SQLite store. Ingest plugin in the personal-finance family - owns `privat_*` tables, standalone, complements `monobank-mcp` without depending on it.

**Features:**
- Drops into `~/finances/inbox/` workflow: export from privat24.ua, drop XLSX, ask Claude "import privat"
- SHA-256 file-level short-circuit so re-importing the same byte sequence skips parsing entirely
- Natural-key dedup (`ts + amount + description + account_id`) so re-exporting overlapping date ranges does NOT create duplicate rows; within-file counter tie-breaks twin transactions
- Europe/Kyiv → UTC conversion via `zoneinfo` (with `tzdata` PyPI fallback for Windows / slim Linux containers)
- Fully atomic schema migration inside one explicit `BEGIN`/`COMMIT` (including the version-tracker bootstrap)
- File archival to `~/finances/archive/YYYY-MM-DD/` on success; source left in place on failure for re-try
- 35 pytest tests covering parser, dedup, store, migrations, integration, currency lookup, plus the new `open_db` error path

**Requirements:** `uv` (Astral's Python toolchain). The skill runs through `uv run --directory ${CLAUDE_PLUGIN_ROOT} privat24-import ...`.

### Personal Finance

Python umbrella skill in the personal-finance family. Queries, reports, and categorizes transactions written by the ingest plugins (`monobank-mcp`, `privat24-skill`) into the shared `~/finances/data.db` SQLite store. Owns `pf_*` tables (categorization rules, manual overrides) and reads `<bank>_transactions` via runtime UNION ALL discovery, so it works with any subset of ingest plugins installed.

**Features:**
- 4 CLI entry points: `pf-query` (accounts, list, summarize, find), `pf-report` (full or bucketed bundle with previous-period comparison), `pf-categorize` (rule-based pass over uncategorized rows), `pf-rules` (add, apply, set-category, set-override, list, reload)
- 4-source rule loader with unified priority (description regex 100 < counterparty 200 < MCC 300 < explicit DB priority); bundled seed rules ship inside the package, user-local YAMLs at `~/finances/rules/` are gitignored and silently optional
- Manual overrides are UPSERTed into `category_overrides` on every `pf-categorize` run; rule pass and overrides import are two separate transactions, both idempotent, safe to retry after a crash
- `pf-rules add` validates regex via `re.compile` BEFORE the INSERT - a typo lands as a clean error instead of a silently non-matching rule
- Same JSON-on-stdout output contract as the ingest plugins (success exit 0; `CliError` JSON on stderr exit 1; uncaught traceback + structured error exit 2)
- 116 pytest tests covering store, view discovery, queries, reports, rules, categorizer, and end-to-end CLI

**Requirements:** `uv` and Python >= 3.13. At least one ingest plugin (`monobank-mcp` and/or `privat24-skill`) installed and populated; the umbrella is read-only against `<bank>_transactions` tables.

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

# Install Monobank MCP (prebuilt binary auto-fetched on first session)
/plugin install monobank-mcp@ai-engineering-skills

# Install Privat24 Skill (Python; needs `uv` on the host)
/plugin install privat24-skill@ai-engineering-skills

# Install Personal Finance umbrella (Python; needs `uv` and >=1 ingest plugin)
/plugin install personal-finance@ai-engineering-skills
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

**Monobank MCP**: After install run `/monobank-mcp:setup`. The wizard walks you through the QR-code flow at <https://api.monobank.ua/> (open the page, click "Get a token", scan the QR with your Monobank mobile app, approve in-app) and stashes the resulting token in Keychain on macOS or `.envrc` / env var on Linux. Then run `monobank-mcp backfill --from 2024-01-01` once from a terminal (respects the 1 req/60s rate limit), and afterwards ask Claude "sync mono" or "show last week" - the `ensure_synced` tool fires inline.

**Privat24 Skill**: Export the XLSX from Privat24 (open <https://next.privat24.ua/wallet>, click the card, stay on **Історія**, click the **"Експорт у XLS"** icon between the search field and **Фільтр** - see [Exporting a statement](./privat24-skill/README.md#exporting-a-statement) for the click-by-click flow). Drop the file into `~/finances/inbox/` and tell Claude "import privat". The skill runs `privat24-import import-inbox`, dedupes against prior runs by SHA, parses the file, and archives the source under `~/finances/archive/YYYY-MM-DD/`.

**Personal Finance umbrella**: install the `personal-finance` skill alongside one or both ingest plugins. It auto-detects whichever `<bank>_transactions` tables are present; ask Claude things like "звіт за квітень", "скільки витратив на каву минулого місяця", "категоризуй транзакції". See [personal-finance README](./personal-finance/README.md) for the full CLI surface (`pf-query`, `pf-report`, `pf-categorize`, `pf-rules`).

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
├── monobank-mcp/                 # Monobank MCP plugin (Rust binary)
│   ├── Cargo.toml                # rmcp + reqwest + rusqlite + keyring
│   ├── schema/
│   │   └── mono_001_initial.sql  # Embedded via include_str!
│   ├── src/                      # main.rs, api.rs, store.rs, sync.rs,
│   │                             # backfill.rs, migrations.rs,
│   │                             # config.rs, error.rs, util/, mcp/
│   ├── scripts/                  # launch.sh + install-binary.sh
│   ├── hooks/hooks.json          # SessionStart -> install-binary.sh
│   ├── commands/setup.md         # /monobank-mcp:setup wizard
│   ├── tests/                    # api_mock + store + sync_resume + ...
│   └── .mcp.json                 # MCP server registration
├── privat24-skill/               # Privat24 Skill plugin (Python)
│   ├── pyproject.toml            # openpyxl + tzdata
│   ├── src/privat24_import/
│   │   ├── __main__.py           # CLI entry (privat24-import)
│   │   ├── parsers/              # detect.py, web_xlsx.py
│   │   ├── core/                 # store.py, dedup.py, currencies.py
│   │   └── schema/               # privat_001_initial.sql + __init__.py
│   ├── skills/privat24-import/SKILL.md
│   ├── fixtures/                 # generate.py + sample_web.xlsx (synthetic)
│   ├── tests/                    # 35 pytest tests
│   └── examples/workflow.md
├── personal-finance/             # Personal Finance umbrella plugin (Python)
│   ├── pyproject.toml            # pyyaml; Python >= 3.13
│   ├── src/pf_skill/
│   │   ├── query.py report.py    # read CLI entry points
│   │   ├── categorize.py rules_cli.py  # write CLI entry points
│   │   ├── schema/               # pf_001_initial.sql + __init__.py
│   │   ├── rules/                # mcc.json + description.yaml seed
│   │   └── common/               # store, view, queries, reports, rules,
│   │                             # categorizer, cli, currencies, types
│   ├── skills/personal-finance/SKILL.md
│   ├── commands/categorize.md
│   ├── examples/                 # backup_db.sh + launchd plist (opt-in)
│   └── tests/                    # 116 pytest tests
├── docs/
│   ├── transactions-schema.md   # Cross-plugin row-shape contract
│   └── pre-publish-checklist.md
└── README.md                     # This file
```

## Release infrastructure

`.github/workflows/release-icloud-mcp.yml` and `.github/workflows/release-monobank-mcp.yml` build prebuilt binaries for 4 targets (darwin arm64/x64, linux x64/arm64) on every matching `<plugin>-v*` tag push. All third-party actions are pinned to commit SHAs; Dependabot (`.github/dependabot.yml`) keeps them current via weekly PRs.
