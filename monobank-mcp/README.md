# monobank-mcp

Local MCP server + CLI for the [Monobank Personal API](https://api.monobank.ua/docs/). Pulls statements into the shared `~/finances/data.db` SQLite store so the [personal-finance](../personal-finance/README.md) umbrella plugin can query, categorise, and report across all your banks.

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

## Getting a Personal API token

Monobank issues per-user "personal" API tokens through a QR-code flow that
requires the Monobank mobile app. There is no email/password login or
self-service web form.

1. Open <https://api.monobank.ua/> in any browser.
2. Click **"Get a token"**. The page shows a QR code.
3. Open the Monobank mobile app, scan the QR, and approve the access
   request inside the app. Monobank may prompt you to confirm the
   permissions granted (`personal-finance` read).
4. The browser flips to a success page showing the token (a string that
   begins with `u`, ~44 chars). Copy it - this is the only time it is
   displayed.

The token is single-purpose: it grants read-only access to your
statements and `/personal/client-info`. It can be revoked at any time
from the same page; minting a new one invalidates the old.

For full Monobank API documentation see
[`https://api.monobank.ua/docs/`](https://api.monobank.ua/docs/).

## Quick start

1. Install the plugin (via `/plugin install monobank-mcp@ai-engineering-skills` or marketplace UI). Prebuilt binaries auto-download on first session for `darwin arm64/x64` and `linux x64/arm64`; other targets fall back to a local `cargo build` which needs a Rust toolchain from <https://rustup.rs>.
2. Run `/monobank-mcp:setup` in a Claude Code session. The wizard:
   - walks you through the token-minting flow above,
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
| `get_sync_status`   | Cursor + gap per account, plus balance reconciliation.               |
| `list_mono_accounts`| Diagnostic listing; not the cross-bank account listing.              |

### Reading an `ensure_synced` response

**`caught_up: true` is the only field that means "the local DB covers everything up to now".** It requires every account to have been walked to the end: no errors, `remaining_chunks: 0` everywhere.

**`rows_added: 0` proves nothing on its own.** The engine emits it both for "queried the window, Monobank returned nothing" and for "never queried this account". Each `per_account` entry carries a `status` that separates them:

| `status`        | API called? | Meaning                                                          |
|-----------------|-------------|------------------------------------------------------------------|
| `synced`        | yes         | Every chunk fetched. `rows_added: 0` here really means empty.     |
| `partial`       | yes         | Some chunks fetched, some left by the wall-clock budget.          |
| `unattempted`   | **no**      | Budget ran out first. This account was not looked at.             |
| `failed`        | attempted   | A chunk errored; the rest of the account was skipped.             |
| `skipped_fresh` | no          | Synced inside `sync_freshness_skip_seconds`; the window is covered.|
| `up_to_date`    | no          | Cursor already at now; nothing to fetch.                          |
| `seeded`        | no          | New account, cursor seeded at now. History needs `backfill`.       |

`chunks_total` / `chunks_fetched` / `remaining_chunks` carry the same information numerically (`chunks_total == chunks_fetched + remaining_chunks`). `gap_seconds` is cursor lag, kept for diagnostics only - it measures how far behind the cursor is, not whether the window has been checked.

When `caught_up` is false, re-invoke `ensure_synced` or run `monobank-mcp sync` from the CLI. Accounts are served **stalest cursor first** (0.4.0+), so successive budget-limited calls rotate through all of them instead of re-serving the same first two.

`estimated_catch_up_seconds` (0.4.2+) prices that choice: `remaining_chunks` times the API interval, so a caller does not have to know the rate limit to decide. Monobank allows one statement call per interval (61s in practice), which means a 90-second MCP budget covers one or two accounts per invocation regardless of how the call is written. On a store with eight stale accounts the estimate comes back near 480s - four or five round trips of `ensure_synced` for what one background `monobank-mcp sync` finishes in a single run. When the estimate exceeds the budget you can afford, go to the CLI instead of re-invoking.

### Balance reconciliation

Monobank stamps every statement row with the account balance after that operation. `ensure_synced` and `get_sync_status` compare that running balance on the newest stored transaction against `mono_accounts.balance_minor` from client-info (0.4.0+):

- `suspected_missing_rows: true` (`balance_matches_last_tx: false`) - the two disagree while the balance snapshot is the fresher of the two. Rows are **provably missing** inside a window the cursor has already passed. Syncing more will not recover them; run `monobank-mcp backfill --from <date> --account <id>`.
- `balance_matches_last_tx: null` - not comparable, which is **not** the same as fine. Either no client-info refresh has ever run, or the snapshot predates the newest stored row (`verdict: snapshot_stale`). Sync never refreshes the snapshot; run `monobank-mcp accounts` to make the check conclusive.

This is deliberately independent of `caught_up`: the cursor can be perfectly current while rows are missing behind it, and the two conditions have different remedies.

`list_mono_accounts` includes `balance_minor`, `credit_limit_minor`, and `balance_synced_at` (0.3.0+). These come from `/personal/client-info` and are refreshed by `monobank-mcp accounts` / backfill, NOT by sync - `balance_synced_at` dates the value. Monobank's balance INCLUDES the credit line, so real funds = `balance_minor - credit_limit_minor`.

### Breaking change in 0.4.0

`caught_up` changed meaning. In 0.3.0 it was true whenever every account's cursor was within 24 hours of now, regardless of whether any chunk had actually been fetched, so a run that ran out of budget before touching an account still reported `caught_up: true`. A monthly report built on that answer was missing 22 hours of spending on the busiest card. From 0.4.0 `caught_up` requires `remaining_chunks == 0` on every account and there is no gap tolerance. The "cursor trails by seconds after a complete sync" case that the tolerance was meant to cover is handled by `sync_freshness_skip_seconds`, which skips the API call and reports `remaining_chunks: 0` honestly.

Consumers that treated `partial: true` + `rows_added: 0` as "already current" must stop; read `caught_up` and per-account `status` instead. All other fields are unchanged; `status`, `chunks_total`, `chunks_fetched`, `balance_checks`, `suspected_missing_rows`, and `accounts_with_suspected_gaps` are additive.

## Key invariants

- **Per-chunk atomicity**: INSERT OR IGNORE on `mono_transactions` and the UPSERT on `mono_sync_state` share one SQLite transaction. A kill mid-chunk never leaves the cursor ahead of the data.
- **Idempotent migrations**: each migration runs inside an explicit `BEGIN`/`COMMIT`. The version-tracker row lands atomically with the schema.
- **Stable ids**: `mono_<api_id>` everywhere, with `INSERT OR IGNORE` for cross-run dedup.
- **Auto-seed sync** (0.2.0+): `monobank-mcp sync` against a fresh account (no prior backfill) seeds the cursor at `now` and returns a clean outcome instead of erroring. Run `backfill --from <date>` explicitly when historical rows matter.
- **Freshness skip** (0.2.0+): repeat syncs within `sync_freshness_skip_seconds` (default 300) skip API calls entirely - no surprise 8 × 61s waits on rapid retries. This is the *only* tolerance for a trailing cursor, and it reports `remaining_chunks: 0` truthfully because the window really is covered.
- **No silent "up to date"** (0.4.0+): `caught_up` is false while any account has an unfetched chunk, and an account that was never contacted reports `status: unattempted` rather than an ambiguous `rows_added: 0`.
- **No starvation** (0.4.0+): accounts are synced stalest-cursor-first, so a wall-clock budget that affords two API calls still reaches every account across successive invocations.
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
