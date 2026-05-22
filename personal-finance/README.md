# personal-finance

Umbrella skill in the personal-finance plugin family. Queries, reports, and categorizes transactions written by the ingest plugins into the shared `~/finances/data.db` SQLite store.

Owns the `pf_*` tables (categorization rules, per-transaction overrides). Reads `<bank>_transactions` / `<bank>_accounts` tables via runtime UNION ALL discovery - no static knowledge of which ingest plugins are installed.

## CLI surface

- `pf-query` - `accounts`, `list`, `summarize`, `find` (read-only)
- `pf-report` - full or bucketed report bundle with optional previous-period comparison
- `pf-categorize` - run the rule-based categorizer pass (`--scope all|last-n-days [--n N]`)
- `pf-rules` - `add`, `apply`, `set-category`, `set-override`, `reload`, `list`

## Seed rules

- `src/pf_skill/rules/mcc.json` - hand-curated MCC -> Ukrainian category map (priority 300)
- `src/pf_skill/rules/description.yaml` - global brand regexes (priority 100)
- `~/finances/rules/counterparty.local.yaml` - user-local merchants (priority 200, gitignored)
- `~/finances/rules/overrides.local.yaml` - per-tx pins UPSERTed into `category_overrides` on every `pf-categorize` run (gitignored)
- `categorization_rules` table - rules added via `pf-rules add`

## Architecture

```
       Claude Code
        |       |
  MCP   |       |  Bash invocations
        v       v
+--------+   +------------------------+
| mono   |   | personal-finance       |
| -mcp   |   | (skill + Python uv)    |
| (Rust) |   | owns pf_*, reads       |
|        |   | mono_* + privat_*      |
+---+----+   +----+-------------+-----+
    |             |             ^
    | writes      | reads       | writes pf_*
    | mono_*      v             v
    v        +---+---------+----+--+
+--------+   |  ~/finances/data.db |
|        |   |  (SQLite WAL)       |
+--------+   +---------+-----------+
                       ^
                       | writes privat_*
              +--------+--------+
              | privat24-skill  |
              | (Python uv)     |
              +-----------------+
```

Cross-plugin row shape: `docs/transactions-schema.md` (v1.0).
Design rationale: `docs/personal-finance-design.md` (v3.0).

## Build / test

```bash
uv sync
uv run pytest -q
uv run ruff check src tests
```

The package follows the same layout as `privat24-skill`:
- `src/pf_skill/common/` - shared modules (store, view, queries, reports, rules, categorizer, cli, types, currencies)
- `src/pf_skill/schema/pf_001_initial.sql` - migration (loaded via `importlib.resources`)
- `src/pf_skill/rules/{mcc.json, description.yaml}` - seed rule data (importlib.resources)
- `src/pf_skill/{query, report, categorize, rules_cli}.py` - argparse entry points exposed via `[project.scripts]`

## Output contract (same across every `pf-*` script)

- Success: JSON on stdout, exit 0
- Known failure (bad args, IO, locked DB): `{"ok": false, "error": "...", "type": "..."}` on stderr, exit 1
- Uncaught bug: traceback on stderr, exit 2

## Path conventions

- DB: `$MONOBANK_MCP_DATA_DIR/data.db` or `~/finances/data.db`. Same env var as the ingest plugins so one setting reroutes everyone.
- Time arguments: unix seconds or ISO 8601 (date or datetime). Naive times treated as UTC.
- Currency arguments: alpha-3 (`UAH`) or ISO numeric (`980`).
