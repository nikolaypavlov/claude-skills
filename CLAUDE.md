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
- **Monobank MCP** (`monobank-mcp/`) -- Local Rust MCP server + CLI for the Monobank Personal API. Ingest plugin in the personal-finance design: owns `mono_*` tables in the shared `~/finances/data.db` SQLite store. Tool surface, CLI, and configuration are documented in the "Monobank MCP Development" section below.
- **Privat24 Skill** (`privat24-skill/`) -- `uv`-managed Python skill that imports Privat24 web-cabinet XLSX statement exports into the shared `~/finances/data.db`. Owns `privat_*` tables. Standalone (works without monobank-mcp or the personal-finance umbrella). Package layout and conventions are in the "Privat24 Skill Development" section below.

**Cross-plugin design**: `docs/personal-finance-design.md` (v2.1) describes the 3-plugin architecture; `docs/transactions-schema.md` (v1.0) is the cross-plugin contract that monobank-mcp and privat24-skill follow for their `<bank>_transactions` shapes.

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

## Personal Finance Architecture

Three plugins share `~/finances/data.db` (SQLite, WAL) by partitioning the table namespace:

| Plugin           | Language | Owns                          | Touches                              |
|------------------|----------|-------------------------------|--------------------------------------|
| `monobank-mcp`   | Rust     | `mono_*`                      | only `mono_*`                        |
| `privat24-skill` | Python   | `privat_*`                    | only `privat_*`                      |
| `personal-finance` (TBD, PR#3) | Python | `pf_*` (categorization rules / overrides) | reads `mono_*` + `privat_*` via runtime UNION ALL discovery |

Each ingest plugin migrates only its own tables. The umbrella plugin auto-detects available `<bank>_transactions` tables via `sqlite_master` and builds a UNION ALL view at query time. The shared row shape (signed minor units, ISO 4217 numeric currency codes, `<bank>_<native_id>` ids) is documented in `docs/transactions-schema.md` and enforced by convention - not by code.

**Atomicity contracts** that every store implementation must hold:
- INSERTs and sync-cursor / version-row updates share one explicit `BEGIN`/`COMMIT` transaction. A kill mid-chunk never leaves a half-applied state.
- Migrations run inside an explicit transaction; PRAGMAs that can't live in a transaction (`journal_mode`) are set on the connection before the migration. Python: avoid `sqlite3.Connection.executescript` - it issues an implicit COMMIT first.
- IDs are globally unique with a per-bank prefix (`mono_<api_id>`, `privat_h_<sha16>`), and ingests use `INSERT OR IGNORE` so re-pulling / re-importing is idempotent.

## iCloud MCP Development

Rust binary plugin. Not a skill - it ships as a standalone MCP server registered via `icloud-mcp/.mcp.json`, which spawns `scripts/launch.sh` (a thin wrapper that ensures the binary is on disk via `install-binary.sh`, then `exec`s it). The wrapper exists because `SessionStart` hooks fire only on new sessions, not on `/reload-plugins`, so the MCP transport could otherwise race the hook and surface `ENOENT`.

**Build:**
```bash
cd icloud-mcp && cargo build --release
```

The binary lands at `icloud-mcp/target/release/icloud-mcp`. For plugin users it ships prebuilt from GitHub Releases; `.mcp.json` resolves to it indirectly through `scripts/launch.sh`.

**Key files:**
- `src/main.rs` -- entry point, `IcloudServer` struct with `#[tool_router]`, 10 tools (incl. `auth_status`), `--probe` CLI mode, stdio transport
- `src/caldav.rs` -- thin wrapper around `libdav::CalDavClient` (list_calendars, list_events, get_event, search_events, create_event)
- `src/imap_client.rs` -- `async-imap` over `tokio-rustls` (list_folders, search, get_message, create_draft via APPEND)
- `src/config.rs` -- env-or-Keychain credential loading
- `src/error.rs` -- McpError helpers
- `scripts/launch.sh` -- runs `install-binary.sh` then `exec`s the binary; referenced by `.mcp.json`
- `scripts/install-binary.sh` -- idempotent: downloads release tarball matching `Cargo.toml` version, verifies SHA256, falls back to `cargo build` if no prebuilt artifact for the platform
- `hooks/hooks.json` -- `SessionStart` hook that pre-warms the binary so the first MCP tool call is not the one paying the download cost
- `commands/setup.md` -- `/icloud-mcp:setup` interactive wizard for first-time credential capture

**Configuration:** Environment variables `APPLE_ID` and `APPLE_APP_PASSWORD` (a 16-char app-specific password from account.apple.com). On macOS, password can also live in Keychain under service `icloud-mcp`, account `$APPLE_ID`.

**Design constraint:** No SMTP. Drafts are APPENDed to the IMAP Drafts folder with the `\Draft` flag; the user reviews and sends them manually in iCloud Mail. This keeps the server from producing external side-effects.

## Rust binary plugin releases

Both Rust plugins (`icloud-mcp`, `monobank-mcp`) follow the same tag-driven release pattern. There are two workflows - `.github/workflows/release-icloud-mcp.yml` and `release-monobank-mcp.yml` - that are structural copies; bug fixes to one usually apply to the other.

To cut a new version of `<plugin>`:

1. Bump `<plugin>/Cargo.toml`, `<plugin>/Cargo.lock`, and `.claude-plugin/marketplace.json` (matching entry) to the same version.
2. Commit with a message referencing the version.
3. `git tag <plugin>-v<X.Y.Z> && git push origin <plugin>-v<X.Y.Z>`.
4. Workflow builds 4 targets in parallel (macos-26 host cross-compiles to both darwin arches, ubuntu-24.04 + ubuntu-24.04-arm for Linux), packages tar.gz, publishes Release with SHA256SUMS.

The workflow asserts that the pushed tag equals `<plugin>-v${CRATE_VERSION}` and fails fast otherwise, so a version-marker drift between `Cargo.toml` and the tag is caught immediately rather than producing artifacts under the wrong name.

All third-party actions in both workflows are pinned to commit SHAs (not tags) with a human-readable version comment, per supply-chain hardening. Dependabot (`.github/dependabot.yml`) opens weekly PRs to bump SHAs as upstream cuts releases.

## Monobank MCP Development

Rust binary plugin. Same shipping pattern as `icloud-mcp` (`.mcp.json` -> `scripts/launch.sh` -> `scripts/install-binary.sh` -> binary). 4-target prebuilt artifacts plus cargo fallback for other platforms.

**Build:**
```bash
cd monobank-mcp && cargo build --release
cargo fmt --check && cargo clippy --all-targets -- -D warnings
cargo test    # 22 unit + 13 integration tests
```

**Key files:**
- `src/main.rs` -- clap dispatch over `init` / `accounts` / `backfill` / `sync` / `serve` / `--probe`; defaults to `serve` (MCP stdio) when no subcommand
- `src/api.rs` -- thin reqwest wrapper around `api.monobank.ua` with `X-Token` auth; UTF-8-safe error-body truncation
- `src/store.rs` -- `rusqlite` store; per-chunk atomic INSERT OR IGNORE + sync-cursor UPSERT
- `src/sync.rs` -- shared engine for CLI `sync` and MCP `ensure_synced`; deadline-bounded, configurable `retry_backoff`
- `src/backfill.rs` -- cold-start backfill, resumable on Ctrl-C
- `src/migrations.rs` -- embeds `schema/mono_001_initial.sql` via `include_str!`; applies inside explicit `BEGIN`/`COMMIT` (NOT `execute_batch` - it auto-commits)
- `src/mcp/tools.rs` -- 3 `#[tool]` methods + setup-required error wiring
- `src/util/ratelimit.rs` -- shared 1 req / 60s token bucket via `tokio::sync::Mutex`
- `schema/mono_001_initial.sql` -- `mono_accounts`, `mono_transactions`, `mono_sync_state`, `mono_import_runs`, `mono_schema_version`. PRAGMAs live in `store.rs::init`, NOT here (journal_mode can't change inside a tx)

**Configuration:** `MONOBANK_TOKEN` env var primary, OS keychain fallback (service `monobank-mcp`, account `api-token`) via the `keyring` crate. Optional `~/finances/config.toml` overrides `data_dir`, `api_base`, `api_min_interval_seconds`, `ensure_synced_default_budget`, `sync_freshness_skip_seconds`.

**Behavioural notes worth knowing:**
- `monobank-mcp sync` against a fresh account (no prior backfill) auto-seeds the cursor at `now` rather than erroring. Run `backfill --from <date>` explicitly for historical rows.
- `ensure_synced` returns `partial: true` when the wall-clock budget expires; Claude is expected to re-invoke or tell the user to run the CLI.
- `--probe` exits non-zero on any failure (auth / config / connectivity) so shell wrappers can detect failure via `$?` without re-parsing JSON.

## Privat24 Skill Development

Python skill, `uv`-managed. Imports XLSX exports from `privat24.ua/statement` into the shared store. Owns `privat_*` tables.

**Build / test:**
```bash
cd privat24-skill && uv sync
uv run pytest -q                          # 35 tests
uv run ruff check src tests fixtures
uv run python fixtures/generate.py        # regenerate synthetic XLSX fixture
```

**Package layout (matters because of `importlib.resources`):**
```
privat24-skill/
  pyproject.toml                          # uv-managed; deps: openpyxl, tzdata
  skills/privat24-import/SKILL.md         # how Claude invokes the CLI
  src/privat24_import/
    __main__.py                           # CLI entry; `uv run privat24-import import <file>`
    parsers/{detect, web_xlsx}.py
    core/{store, dedup, currencies}.py    # NOTE: named `core/` not `lib/` because the
                                          # root .gitignore drops `lib/` (Python venv pattern)
    schema/privat_001_initial.sql         # in-package; loaded via importlib.resources so
                                          # the wheel layout works too. pyproject.toml has
                                          # [tool.setuptools.package-data] for *.sql.
  fixtures/{generate.py, sample_web.xlsx} # seeded RNG; never edit XLSX by hand
  tests/                                  # detect / parse / dedup / store / migrations /
                                          # integration / currencies
```

**Conventions specific to this skill:**
- Migration applies via individual `conn.execute(stmt)` calls inside a `BEGIN`/`COMMIT`. DO NOT switch to `executescript` - per the stdlib docs it issues an implicit COMMIT first and silently closes the explicit `BEGIN`.
- Naive Privat24 timestamps are Europe/Kyiv; the parser attaches `ZoneInfo("Europe/Kyiv")` so stored unix is true UTC. `tzdata>=2024.1` is a hard runtime dep for Windows / slim Linux containers.
- Account upsert and tx INSERTs share one transaction via `insert_transactions(account=AccountSpec)`. A failure rolls back both - no dangling account rows.
- `ImportResult` is a `TypedDict` with `Literal["imported", "skipped", "unsupported", "error"]` status. Pre-flight I/O failures (missing file, unwritable data dir) land as `status: error` JSON, not as a traceback escaping stdout.
- Fixture file is regenerated via `fixtures/generate.py`; the committed `sample_web.xlsx` is the canonical reference for tests.

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
- Python code uses full type annotations; `jira-manager` tools return `(success: bool, message: str, data: Optional)` tuples on stdin/stdout JSON
- CLI tools communicate via JSON on stdin/stdout
- Each plugin owns its own test suite where the language supports it:
  - Rust plugins: `cargo test` (icloud-mcp, monobank-mcp)
  - Python `uv` plugins: `uv run pytest -q` (privat24-skill; jira-manager has a `tests/` dir but most of its testing is manual via example scripts)
  - Documentation-only skills (nemo-builder, acli-manager, pdf-design-system) have no test suite

### Developer gotchas

- **`.mcp.json` plugin-vs-project duplication**: Claude Code discovers `<rust-plugin>/.mcp.json` twice when a contributor has the repo cloned AND the plugin installed - once as plugin (CLAUDE_PLUGIN_ROOT defined, works) and once as project config (variable unset, fails). The plugin instance is the working one. To silence the noise for each affected plugin, extend `disabledMcpjsonServers` in `.claude/settings.local.json` (e.g. `["icloud", "monobank"]`).
- **gh CLI auth is ephemeral in dev containers**: pushing to main with workflow file changes requires `workflow` scope on the gh token (`gh auth refresh -h github.com -s workflow`). Plain `gh auth login` only gives `gist, read:org, repo`.
- **Privat24 timezones require `tzdata`**: `ZoneInfo("Europe/Kyiv")` would raise `ZoneInfoNotFoundError` on Windows / slim Linux containers without the OS tz database, so `privat24-skill/pyproject.toml` pins `tzdata>=2024.1`. If you ever drop the dep, the CLI fails at module import, before any JSON output - the SKILL.md stdout contract relies on this.
- **Shared SQLite store is single-machine, single-user**: `~/finances/data.db` must not live on shared / cloud storage when more than one process can write. WAL is enabled defensively but cross-machine concurrent writes still corrupt SQLite.

### Rust projects

Every Rust crate in this repo must pass `cargo fmt`, `cargo clippy`, and `cargo test` before commit:

```bash
cargo fmt --check
cargo clippy --all-targets -- -D warnings
cargo test
```

Rules:
- Each Rust crate has a `rustfmt.toml` (or inherits sensible defaults) and pins lint policy in `Cargo.toml` under `[lints]` -- at minimum `unsafe_code = "forbid"` under `[lints.rust]` and `clippy::all = warn` (with `priority = -1`) under `[lints.clippy]`.
- Fix clippy warnings rather than suppressing them. Use `#[allow(...)]` only with a comment explaining why.
- Run `cargo fmt` after any code change. Do not hand-format -- let rustfmt own layout.
- `cargo build --release --locked` must succeed warning-free before pushing.
- New test files for critical invariants (atomicity, retry behaviour, schema migrations) belong in `tests/` (integration) rather than `#[cfg(test)] mod tests` blocks - integration tests are also what the release workflow runs.
