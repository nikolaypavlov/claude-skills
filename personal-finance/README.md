# personal-finance

Umbrella Claude Code plugin for cross-bank queries over the shared
`~/finances/data.db` SQLite store. Reads `<bank>_transactions` /
`<bank>_accounts` tables produced by ingest plugins
(`monobank-mcp`, `privat24-skill`) via runtime sqlite_master discovery
and projects them through a UNION ALL view. Owns `pf_*` tables for
categorization rules and manual overrides.

This is the third plugin in the personal-finance design
(`docs/personal-finance-design.md`); the ingest plugins are
prerequisites but the umbrella detects them dynamically - you can
install in any order and the surface adapts to whatever is present.

## Architecture

```
+-------------------+   +------------------+   +---------------------------+
|  monobank-mcp     |   | privat24-skill   |   |    personal-finance       |
|  (Rust, owns      |   | (Python, owns    |   |    (Python MCP, owns      |
|   mono_*)         |   |  privat_*)       |   |    pf_*, reads both       |
+--------+----------+   +---------+--------+   +-------------+-------------+
         |                        |                          |
         v                        v                          v
+------------------------------------------------------------------------+
|                  ~/finances/data.db  (SQLite, WAL)                     |
+------------------------------------------------------------------------+
```

## Quick start

1. Install `uv` if you don't already have it (`brew install uv` or the
   official installer).
2. Install at least one ingest plugin so the store contains real data:
   - `/plugin install monobank-mcp@ai-engineering-skills` -> run
     `/monobank-mcp:setup` -> run `monobank-mcp backfill --from <date>`
   - `/plugin install privat24-skill@ai-engineering-skills` -> drop a
     Privat24 XLSX into `~/finances/inbox/` and ask Claude
     "import privat"
3. Install this plugin: `/plugin install personal-finance@ai-engineering-skills`
4. Ask Claude something like "list my accounts" or "show last week's
   spending" - the umbrella's `personal-finance` MCP server auto-spawns
   on first tool call.

## MCP tools (0.1.0)

| Tool                  | Status   | What |
|-----------------------|----------|------|
| `data_sources`        | 0.1.0    | Diagnostic: list detected ingest plugins + pf_* schema version. |
| `list_accounts`       | 0.1.0    | Every account across every installed ingest plugin. |
| `get_transactions`    | 0.1.0    | Cross-bank query with filters + pagination; resolves category (override > rule > NULL). |
| `summarize_spending`  | 0.1.0    | Aggregate by category / mcc / counterparty / currency / account / bank. Per-currency totals. |
| `find_transaction`    | PR#4     | Description-substring search. |
| `get_report_bundle`   | PR#4     | Full report bundle (per-currency, comparison vs prior period, top counterparties, recurring). |
| `set_category`        | PR#4     | Pin a manual category on a tx. |
| `add_rule`            | PR#4     | Add a categorization rule (preview-only). |
| `reload_rules`        | PR#4     | Reload from YAML + DB sources. |
| `apply_rules_retroactively` | PR#4 | Apply a rule to historical txs. |
| `categorize_uncategorized`  | PR#4 | Sweep + categorize per the rule set. |

PR#4 tools are currently registered so the surface is visible from
discovery; calling them raises a clean `"ships in PR#4"` error.

## CLI

```bash
uv run --directory <path-to-personal-finance> pf-cli sources
uv run --directory <path-to-personal-finance> pf-cli accounts
uv run --directory <path-to-personal-finance> pf-cli transactions \
  --from-ts 1750000000 --bank mono --limit 50
```

`pf-cli` is a thin wrapper around the same query helpers the MCP tools
call - useful for ad-hoc inspection without spawning a full MCP
session.

`pf-server --probe` runs a one-shot health check and prints JSON to
stdout (used by setup wizards).

## Schema ownership

The umbrella owns and migrates ONLY:

- `pf_schema_version` - migration tracker
- `categorization_rules` - regex / mcc -> category rules
- `tx_category` - rule-assigned categories per tx
- `category_overrides` - user-pinned manual categories per tx

It NEVER writes to `mono_*` or `privat_*` tables - those are owned by
their respective ingest plugins. The contract for the
`<bank>_transactions` row shape lives in
[`../docs/transactions-schema.md`](../docs/transactions-schema.md).

## Atomicity contracts

Same as the ingest plugins:

- PRAGMA defaults (WAL, foreign_keys, busy_timeout) set once per
  connection BEFORE migrations.
- Each migration runs inside an explicit `BEGIN`/`COMMIT` built from
  individual `conn.execute` calls (NOT `executescript`, which
  auto-commits).
- The `pf_schema_version` bootstrap CREATE is INSIDE the migration
  transaction, so a kill mid-apply rolls back the tracker too.

## Development

```bash
cd personal-finance
uv sync
uv run pytest -q          # 29 tests
uv run ruff check src tests
uv run pf-cli sources
```
