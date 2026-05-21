# monobank-mcp

Local MCP server + CLI for the [Monobank Personal API](https://api.monobank.ua/docs/). Pulls statements into the shared `~/finances/data.db` SQLite store so the [personal-finance](../docs/personal-finance-design.md) umbrella plugin can query, categorise, and report across all your banks.

This is the **ingest plugin only**. It owns the `mono_*` tables in the shared store and does nothing else. Query, reports, and categorisation live in the personal-finance plugin (separate package).

## Architecture

```
+----------------+        HTTPS (1 req / 60s)        +-----------------+
| Claude Desktop |       <----- statements -----     | api.monobank.ua |
+-------+--------+                                   +-----------------+
        | MCP stdio                                          ^
        v                                                    |
+--------+----------+        CLI                             |
|  monobank-mcp     |  (init / backfill / sync)              |
|  (Rust binary)    +----------------------------------------+
|  - ensure_synced  |
|  - get_sync_status|        rusqlite (INSERT OR IGNORE)
|  - list_mono_     +-------> ~/finances/data.db
|    accounts       |           mono_accounts
+-------------------+           mono_transactions
                                mono_sync_state
                                mono_import_runs
                                mono_schema_version
```

## Quick start

1. Install the plugin (via `/plugin install monobank-mcp@ai-engineering-skills` or marketplace UI). Prebuilt binaries auto-download on first session for `darwin arm64/x64` and `linux x64/arm64`; other targets fall back to a local `cargo build` which needs a Rust toolchain from <https://rustup.rs>.
2. Run `/monobank-mcp:setup` in a Claude Code session. The wizard:
   - prompts for a token from <https://api.monobank.ua/>,
   - stores it (macOS Keychain, `launchctl`, project `.envrc`, or pasted exports),
   - probes the connection with one `/personal/client-info` call (exit-coded so shell wrappers can detect failure without parsing JSON).
3. After setup, run a one-time backfill from a terminal:
   ```bash
   "${CLAUDE_PLUGIN_ROOT}/target/release/monobank-mcp" backfill --from 2024-01-01
   ```
   (Take a coffee. Backfill respects the 1 req/60s rate limit, so 12 months ≈ 12 minutes per account.)
4. From then on, ask Claude things like "sync mono and show last week" - the `ensure_synced` tool fires inline within the configured `max_wait_seconds` budget (default 90s).

## Tools (MCP)

| Tool                | What                                                                 |
|---------------------|----------------------------------------------------------------------|
| `ensure_synced`     | Inline incremental sync, bounded by `max_wait_seconds` (default 90). |
| `get_sync_status`   | Cursor + gap (seconds to now) per account.                           |
| `list_mono_accounts`| Diagnostic listing; not the cross-bank account listing.              |

## Key invariants

- **Per-chunk atomicity**: INSERT OR IGNORE on `mono_transactions` and the UPSERT on `mono_sync_state` share one SQLite transaction. A kill mid-chunk never leaves the cursor ahead of the data.
- **Idempotent migrations**: each migration runs inside an explicit `BEGIN`/`COMMIT`. The version-tracker row lands atomically with the schema.
- **Stable ids**: `mono_<api_id>` everywhere, with `INSERT OR IGNORE` for cross-run dedup.
- **Auto-seed sync** (0.2.0+): `monobank-mcp sync` against a fresh account (no prior backfill) seeds the cursor at `now` and returns a clean outcome instead of erroring. Run `backfill --from <date>` explicitly when historical rows matter.
- **Freshness skip** (0.2.0+): repeat syncs within `sync_freshness_skip_seconds` (default 300) skip API calls entirely - no surprise 8 × 61s waits on rapid retries.
- **Rate-limit retry with bounded backoff**: a 429 / transient error triggers up to 3 retries with a configurable `retry_backoff` (production default 90s; tests pass `Duration::ZERO`).
- **UTF-8 safe error truncation**: API error bodies (often Ukrainian) survive 256-byte truncation without panicking on mid-codepoint slices.

## CLI

```
monobank-mcp init                       # capture token, write config.toml
monobank-mcp accounts                   # refresh local mono_accounts via API
monobank-mcp backfill --from 2024-01-01 # cold-start backfill
monobank-mcp sync                       # incremental sync, no time budget
monobank-mcp serve                      # MCP stdio (default if no subcommand)
monobank-mcp --probe                    # JSON diagnostic, used by /setup
```

## Configuration

Optional `~/finances/config.toml` (auto-created by `init`):

```toml
token_in_keychain = true
# data_dir = "~/finances"
# api_base = "https://api.monobank.ua"
# api_min_interval_seconds = 61
# ensure_synced_default_budget = 90
# sync_freshness_skip_seconds = 300
```

Token resolution order:

1. `MONOBANK_TOKEN` env var
2. Keychain entry (`service=monobank-mcp`, `account=api-token`)
3. Error - run `/monobank-mcp:setup`

## Schema ownership

monobank-mcp owns and migrates **only** `mono_*` tables (`mono_accounts`, `mono_transactions`, `mono_sync_state`, `mono_import_runs`, `mono_schema_version`). It does NOT touch tables owned by other plugins. The cross-plugin convention lives in [`../docs/transactions-schema.md`](../docs/transactions-schema.md).

## Standalone use

The plugin works without `personal-finance` or `privat24-skill` installed: backfill / sync run independently, and the `mono_*` tables are created on first connect. You just won't get cross-bank queries or categorisation until you install the umbrella.

## Development

```bash
cd monobank-mcp
cargo fmt --check
cargo clippy --all-targets -- -D warnings
cargo test
cargo build --release
```

Release is driven by pushing a tag `monobank-mcp-v<X.Y.Z>` matching `Cargo.toml`. See [`../.github/workflows/release-monobank-mcp.yml`](../.github/workflows/release-monobank-mcp.yml).
