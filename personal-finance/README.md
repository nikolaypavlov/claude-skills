# personal-finance

Umbrella skill in the personal-finance plugin family. Queries, reports, and (PR#4) categorizes transactions written by the ingest plugins into the shared `~/finances/data.db` SQLite store.

Owns the `pf_*` tables (categorization rules, per-transaction overrides). Reads `<bank>_transactions` / `<bank>_accounts` tables via runtime UNION ALL discovery - no static knowledge of which ingest plugins are installed.

## What's in PR#3 (this PR)

- `pf-query` CLI: `accounts`, `list`, `summarize`, `find` (read-only, no writes to `pf_*`)
- `pf-report` CLI: full or bucketed report bundle with optional previous-period comparison
- `skills/personal-finance/SKILL.md` for Claude activation
- `commands/categorize.md` stub (mutations land in PR#4)
- `pf_*` schema migration applied on first read

## What's in PR#4 (next)

- `pf-categorize` CLI (runs the rule-based categorizer pass)
- `pf-rules` CLI (`add`, `apply`, `set-category`, `set-override`, `reload`, `list`)
- `rules/mcc.json` + `rules/description.yaml` seed
- `scripts/build_mcc_map.py`

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
- `src/pf_skill/common/` - shared modules (store, view, queries, reports, cli, types, currencies)
- `src/pf_skill/schema/pf_001_initial.sql` - migration (loaded via `importlib.resources`)
- `src/pf_skill/query.py`, `report.py` - argparse entry points exposed via `[project.scripts]` as `pf-query` and `pf-report`

## Output contract (same across every `pf-*` script)

- Success: JSON on stdout, exit 0
- Known failure (bad args, IO, locked DB): `{"ok": false, "error": "...", "type": "..."}` on stderr, exit 1
- Uncaught bug: traceback on stderr, exit 2

## Path conventions

- DB: `$MONOBANK_MCP_DATA_DIR/data.db` or `~/finances/data.db`. Same env var as the ingest plugins so one setting reroutes everyone.
- Time arguments: unix seconds or ISO 8601 (date or datetime). Naive times treated as UTC.
- Currency arguments: alpha-3 (`UAH`) or ISO numeric (`980`).
