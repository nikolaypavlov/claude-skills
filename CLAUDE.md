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
- **Personal Finance** (`personal-finance/`) -- `uv`-managed Python umbrella skill for query / report / categorize / budget over the shared `~/finances/data.db`. Owns the `pf_*` family of tables (categorization rules + overrides, budgets + drafts, category registry, import audit). Reads `<bank>_transactions` via runtime UNION ALL discovery so it works with any subset of ingest plugins installed. Budget planning is conversation-driven - DB is source of truth, Google Sheets is an on-demand rendered view. Five CLI entry points (`pf-query`, `pf-report`, `pf-categorize`, `pf-rules`, `pf-budget`) follow the same JSON-output contract as the ingest plugins. Layout and rule-loading conventions are in the "Personal Finance Umbrella Development" section below.
- **STE Writing** (`ste-writing/`) -- Prose rewriting into a controlled plain technical style for English (ASD-STE100) and Ukrainian (adapted STE + DSTU 3966:2009), with symmetric strict and STE-flavored modes. Documentation-only skill with per-language rule references.

**Cross-plugin contract**: `docs/transactions-schema.md` (v1.0) is the row-shape contract that monobank-mcp and privat24-skill follow for their `<bank>_transactions` tables; personal-finance reads through it.

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
| `personal-finance` | Python (uv) | `pf_*` (categorization rules / overrides) | reads `mono_*` + `privat_*` via runtime UNION ALL discovery |

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
- `scripts/install-binary.sh` -- idempotent: downloads release tarball matching `Cargo.toml` version, verifies SHA256, falls back to `cargo build` if no prebuilt artifact for the platform. It short-circuits ONLY when the binary already on disk answers `--version` with the `Cargo.toml` version; anything else is deleted and re-fetched. Do not weaken that back to a bare `[[ -x ]]` test - see the gotcha below.
- `hooks/hooks.json` -- `SessionStart` hook that pre-warms the binary so the first MCP tool call is not the one paying the download cost
- `commands/setup.md` -- `/icloud-mcp:setup` interactive wizard for first-time credential capture

**Configuration:** Environment variables `APPLE_ID` and `APPLE_APP_PASSWORD` (a 16-char app-specific password from account.apple.com). On macOS, password can also live in Keychain under service `icloud-mcp`, account `$APPLE_ID`.

**Design constraint:** No SMTP. Drafts are APPENDed to the IMAP Drafts folder with the `\Draft` flag; the user reviews and sends them manually in iCloud Mail. This keeps the server from producing external side-effects.

## Rust binary plugin releases

**Mandatory for every Rust plugin in this repo.** Every Rust crate that ships as a user-installable binary plugin MUST have:

1. A `.github/workflows/release-<plugin>.yml` workflow modeled on `release-icloud-mcp.yml` (the canonical template). Copy it whole-file when adding a new plugin and only change the plugin name + crate path; never invent a new release shape.
2. A `<plugin>/scripts/install-binary.sh` that downloads from the matching `https://github.com/<owner>/<repo>/releases/download/<plugin>-v${version}/` URL and verifies SHA256.
3. A `<plugin>/scripts/launch.sh` referenced from `<plugin>/.mcp.json` that runs `install-binary.sh` then `exec`s the binary.
4. Prebuilt artifacts for all 4 standard targets (darwin arm64/x64, linux x64/arm64) on every released version - i.e. a release tag pushed for every `<plugin>/Cargo.toml` version bump. A cargo-build fallback in `install-binary.sh` is for unsupported platforms, NOT a substitute for missing prebuilt artifacts.
5. The marketplace entry's `version` field in `.claude-plugin/marketplace.json` always matches `<plugin>/Cargo.toml`'s `version`. The workflow's tag assertion catches drift; the matching marketplace entry is the user-facing contract.

Both existing Rust plugins (`icloud-mcp`, `monobank-mcp`) follow this pattern. There are two workflows - `.github/workflows/release-icloud-mcp.yml` and `release-monobank-mcp.yml` - that are structural copies; bug fixes to one usually apply to the other.

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
cargo test    # 24 unit + 18 integration tests
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
- **Only `caught_up: true` means the DB is current** (0.4.0+). `rows_added: 0` is emitted both for "fetched the window, nothing new" and for "never fetched this account"; the per-account `status` (`synced` / `partial` / `unattempted` / `failed` / `skipped_fresh` / `up_to_date` / `seeded`) and `chunks_fetched` are what separate them. Before 0.4.0 `caught_up` used a 24h cursor-lag tolerance and ignored unfetched chunks, which let a budget-starved run report a missing day of spending as up to date.
- Accounts are synced stalest-cursor-first (`Store::list_account_ids_by_staleness`), not by id. The ~2-API-call `ensure_synced` budget would otherwise serve the same first two accounts forever.
- `suspected_missing_rows` compares `mono_accounts.balance_minor` against the running balance on the newest stored transaction. A mismatch means rows are missing inside an already-walked window - `sync` cannot fix it, only `backfill --from`. It is deliberately NOT part of `caught_up`. The snapshot is refreshed by `accounts`/backfill only, so a snapshot older than the newest row reports "unknown", never "matches".
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

## Personal Finance Umbrella Development

Python skill, `uv`-managed. Read-and-write side of the personal-finance loop: owns the `pf_*` family of tables (categorization rules + overrides, budgets + drafts, category registry, import audit), reads ingest plugins' `<bank>_transactions` tables through a runtime-discovered UNION ALL view. Five CLI entry points exposed via `[project.scripts]`; SKILL.md tells Claude which one to invoke for each user phrase.

**Build / test:**
```bash
cd personal-finance && uv sync
uv sync --extra sheets                    # add openpyxl for XLSX paths
uv run pytest -q
uv run ruff check src tests
```

**Package layout:**
```
personal-finance/
  pyproject.toml                          # uv-managed; deps: pyyaml;
                                          # optional [sheets] extra: openpyxl.
                                          # Python >= 3.13
  skills/personal-finance/SKILL.md        # trigger phrases + invocation cookbook
  commands/categorize.md                  # /personal-finance:categorize workflow
  commands/status.md                      # /personal-finance:status workflow
                                          # (sync -> categorize -> gate -> diff -> report)
  src/pf_skill/
    query.py        report.py             # read-only CLI entry points
    categorize.py   rules_cli.py
    budget_cli.py                         # write CLI entry points
    schema/                               # pf_001 .. pf_005 .sql migrations,
                                          # in-package via importlib.resources
    rules/{mcc.json,description.yaml}     # bundled seed rules, importlib.resources
    common/
      store.py     view.py                # SQLite + runtime UNION discovery +
                                          # state-machine SQL splitter
      queries.py   reports.py             # read helpers + report bundle
                                          # (with auto-attached budget block)
      rules.py     categorizer.py         # 4-source rule loader + apply pass
      budget.py                           # planning + lifecycle + scanner +
                                          # CSV/XLSX parsing + family view
      cli.py       currencies.py types.py
  tests/                                  # store / view / queries / reports /
                                          # rules / categorizer / budget
                                          # (schema, import, planning, signals,
                                          # family, export, lifecycle) +
                                          # end-to-end CLI
```

**Conventions specific to this skill:**
- Same atomicity contract as the ingest plugins: `isolation_level = None`, explicit `BEGIN`/`COMMIT`, individual `conn.execute` calls (NEVER `executescript`). Rule pass + overrides import are two SEPARATE transactions inside `apply_rules` - both idempotent (`INSERT OR IGNORE` on `tx_category`, `INSERT OR REPLACE` on `category_overrides`) so a crash between them is safe to retry.
- Rule priority is unified in `common/rules.py::DEFAULT_PRIORITY_BY_FIELD` (counterparty 100 < description 200 < mcc 300 < explicit DB priority). Lower wins; ties broken by source then pattern. `pf-rules add` validates regex via `re.compile` BEFORE the INSERT (MCC patterns skipped - they are exact integer matches). `Rule.matches` swallows `re.error` so a single bad rule does not break the whole `pf-categorize` pass.
- Local YAMLs at `$DATA_DIR/rules/counterparty.local.yaml` and `$DATA_DIR/rules/overrides.local.yaml` are gitignored and silently optional. Overrides are UPSERTed into `category_overrides` on every `pf-categorize` run.
- `common/store.py::_split_statements` is a state-machine SQL splitter that tracks `BEGIN ... END` block depth and single-quoted string literals. It's used by every migration; new migrations with triggers or string-embedded `;` ride on the same code path.
- Budget data lives in `budget` (one row per `(period, currency_code, status)`), `budget_line`, `budget_draft_edit` (per-draft undo log), `category_registry`, `budget_import_run`. Closed-budget triggers block `budget_line` INSERT/UPDATE/DELETE while parent `status='closed'`. Drafts and active budgets coexist for the same `(period, currency_code)` during planning; `commit_draft` swaps them atomically.
- Because drafts and actives coexist, **anything reading `fetch_budget` output must filter blocks by `status`**. `pf-budget show` returns the active AND the draft block side by side while planning is in flight; an unfiltered consumer double-counts every draft line as an active one.
- `start_draft` has two modes and picks by whether `period` already has an active budget (0.7.1+). Own active budget -> copy it in full, every `kind`, `in_place: true` (editing the current month; `commit_draft` replaces the active budget, so a partial copy deletes the omitted lines). No active budget -> new month: most recent prior active period, `kind='baseline'` only, `in_place: false` (one_time belongs to the month it was planned for). `--copy-from` overrides the source; `--copy-from ''` starts blank.
- Currency semantics: `amount_minor` is in the **account** currency. The summary path joins to `<bank>_accounts.currency_code` rather than reading `<bank>_transactions.currency_code` (which is the operation currency). Foreign-merchant rows on a UAH card stay in UAH totals.
- Output contract is shared across every `pf-*` script: success → JSON stdout exit 0; `CliError` → `{"ok": false, "error": ..., "type": ..., "details": {...}}` stderr exit 1; uncaught → traceback + structured error stderr exit 2. `common/cli.py::run_subcommand` is the gate. `details` carries structured payloads (e.g. unknown-category suggestions on budget import) for callers to render rich error messages.
- Budget status reporting leads with coverage: can the money cover the plan. That block is the ONE place currencies are combined - converted at the NBU rate fetched per report (`bank.gov.ua/NBUStatService/v1/statdirectory/exchange?json`, matched on `r030`), labelled as converted, with unconvertible currencies named rather than dropped. Every other section stays in its native currency. `pf-budget diff` has no conversion flag; the report layer does it.
- Planned spend is NOT `totals.target_minor` (that mixes in planned `Дохід/*` rows). Derive it as `real_spend_minor + remaining_minor`.
- Budget planning is conversation-driven. The CLI emits structured signals (`pf-budget plan suggest`) for Claude to phrase; Claude records each user decision as a single `plan add/update/remove` call. `pf-budget import` exists as a side-door for bulk migration but is NOT the conversation path - the planning loop uses single-line edits exclusively.

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

- Plugin version lives in two places: the plugin-internal file (`Cargo.toml` / `pyproject.toml`) AND the matching entry in `.claude-plugin/marketplace.json`. Bump both in the SAME commit. The marketplace JSON is what `/plugin` reports as "latest"; if it lags, `/plugin update` shows stale versions and re-runs of the cached install don't pick up new code.

## Conventions

- SKILL.md files use YAML frontmatter for skill metadata
- Python code uses full type annotations; `jira-manager` tools return `(success: bool, message: str, data: Optional)` tuples on stdin/stdout JSON
- CLI tools communicate via JSON on stdin/stdout
- Each plugin owns its own test suite where the language supports it:
  - Rust plugins: `cargo test` (icloud-mcp, monobank-mcp)
  - Python `uv` plugins: `uv run pytest -q` (privat24-skill, personal-finance; jira-manager has a `tests/` dir but most of its testing is manual via example scripts)
  - Documentation-only skills (nemo-builder, acli-manager, pdf-design-system, ste-writing) have no test suite

### Developer gotchas

- **`.mcp.json` plugin-vs-project duplication**: Claude Code discovers `<rust-plugin>/.mcp.json` twice when a contributor has the repo cloned AND the plugin installed - once as plugin (CLAUDE_PLUGIN_ROOT defined, works) and once as project config (variable unset, fails). The plugin instance is the working one. To silence the noise for each affected plugin, extend `disabledMcpjsonServers` in `.claude/settings.local.json` (e.g. `["icloud", "monobank"]`).
- **A stale binary can outlive a `/plugin update`**: `/plugin update` copies the plugin directory out of `~/.claude/plugins/marketplaces/<mp>/<plugin>/` including git-ignored files, so a `target/release/<plugin>` left behind by an old `cargo build` fallback rides along into the NEW version directory. `git pull` never removes it. Before 0.4.1 / 0.3.5 `install-binary.sh` exited on a bare `[[ -x "$BIN_PATH" ]]`, so a directory labelled `0.4.0` happily ran 0.2.1 code, and icloud-mcp kept a Linux aarch64 ELF installed on a mac where it could not exec at all. Both scripts now compare `--version` output against `Cargo.toml`. If you ever hit a plugin behaving like an older release, check `<cache>/<version>/target/release/<plugin> --version` first, and clear the copy in the marketplace clone too.
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
