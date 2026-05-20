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

1. Install Rust toolchain if you don't have one already: <https://rustup.rs>.
2. Add this plugin via `/plugin install monobank-mcp` (or marketplace UI).
3. Run `/monobank-mcp:setup` in a Claude Code session. The wizard:
   - downloads or builds the binary,
   - prompts for a token from <https://api.monobank.ua/>,
   - stores it (macOS Keychain, `launchctl`, project `.envrc`, or pasted exports),
   - probes the connection with one `/personal/client-info` call.
4. After setup, run a one-time backfill from a terminal:
   ```bash
   ~/.claude/plugins/monobank-mcp/target/release/monobank-mcp \
     backfill --from 2024-01-01
   ```
   (Take a coffee. Backfill respects the 1 req/60s rate limit, so 12 months ≈ 12 minutes per account.)

## Tools (MCP)

| Tool                | What                                                                 |
|---------------------|----------------------------------------------------------------------|
| `ensure_synced`     | Inline incremental sync, bounded by `max_wait_seconds` (default 90). |
| `get_sync_status`   | Cursor + gap (seconds to now) per account.                           |
| `list_mono_accounts`| Diagnostic listing; not the cross-bank account listing.              |

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
