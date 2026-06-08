# personal-finance

Umbrella skill in the personal-finance plugin family. Queries, reports, categorizes, and plans budgets over transactions written by the ingest plugins into the shared `~/finances/data.db` SQLite store.

Owns the `pf_*` family of tables (categorization rules, per-transaction overrides, budgets, drafts, category registry, import audit). Reads `<bank>_transactions` / `<bank>_accounts` tables via runtime UNION ALL discovery - no static knowledge of which ingest plugins are installed.

## CLI surface

- `pf-query` - `accounts`, `list`, `summarize`, `summarize-uncategorized`, `categories`, `find` (read-only)
- `pf-report` - full or bucketed report bundle with optional previous-period comparison and an auto-attached budget block when the period covers one calendar month
- `pf-categorize` - run the rule-based categorizer pass (`--scope all|last-n-days [--n N]`)
- `pf-rules` - `add`, `apply`, `set-category`, `set-override`, `list`
- `pf-budget` - budget feature, two surfaces:
  - **Planning** (conversation-driven): `plan start | suggest | add | update | remove | undo | show | commit | cancel`
  - **Lifecycle / export**: `show | list | diff | close | reopen | delete | rename-category | export | register-category | unregister-category | list-categories | import`

Every script follows the same JSON output contract (success exit 0; `{"ok": false, ...}` on stderr exit 1; uncaught traceback + structured stderr exit 2).

## Architecture

```
       Claude Code
        |       |
  MCP   |       |  Bash invocations
        v       v
+--------+   +------------------------+
| mono   |   | personal-finance       |
| -mcp   |   | (skill + Python uv)    |
| (Rust) |   | owns pf_* + budget*,   |
|        |   | reads mono_* + privat_*|
+---+----+   +----+-------------+-----+
    |             |             ^
    | writes      | reads       | writes pf_* / budget*
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

## Schema

Migrations applied atomically by `common/store.py`:

| Version | File | What it adds |
|---|---|---|
| 1 | `pf_001_initial.sql` | `categorization_rules`, `tx_category`, `category_overrides`, `pf_schema_version` |
| 2 | `pf_002_budget.sql` | `budget`, `budget_line`, `category_registry`, `budget_import_run` |
| 3 | `pf_003_budget_triggers.sql` | closed-budget triggers blocking `budget_line` mutations |
| 4 | `pf_004_budget_draft_edit.sql` | `budget_draft_edit` (per-edit undo log for draft sessions) |
| 5 | `pf_005_budget_unique_per_status.sql` | loosens `budget` UNIQUE to `(period, currency_code, status)` so draft + active coexist during planning |

## Seed rules

- `src/pf_skill/rules/mcc.json` - hand-curated MCC → Ukrainian category map (priority 300)
- `src/pf_skill/rules/description.yaml` - global brand regexes (priority 200)
- `$DATA_DIR/rules/counterparty.local.yaml` - user-local merchants (priority 100, gitignored)
- `$DATA_DIR/rules/overrides.local.yaml` - per-tx pins UPSERTed into `category_overrides` on every `pf-categorize` run (gitignored)
- `categorization_rules` table - rules added via `pf-rules add` (default priority sits below the seeds)

Rule priority is lower-wins; ties are broken by source then pattern.

## Build / test

```bash
uv sync                                  # base install
uv sync --extra sheets                   # adds openpyxl for XLSX read/write paths
uv run pytest -q
uv run ruff check src tests
```

The package follows the same layout as the other Python plugins in this repo:

- `src/pf_skill/common/` - shared modules (store, view, queries, reports, rules, categorizer, budget, cli, currencies, types)
- `src/pf_skill/schema/` - SQL migrations loaded via `importlib.resources`
- `src/pf_skill/rules/{mcc.json, description.yaml}` - seed rule data (`importlib.resources`)
- `src/pf_skill/{query, report, categorize, rules_cli, budget_cli}.py` - argparse entry points exposed via `[project.scripts]`

## Optional dependencies

`openpyxl` is required only for the XLSX paths (`pf-budget import file.xlsx`, `pf-budget export --format xlsx`, `pf-budget export --view family`). CSV paths use stdlib only. Install via `uv pip install pf-skill[sheets]` or add the `sheets` extra to your local `uv sync`.

## Output contract (same across every `pf-*` script)

- Success: JSON on stdout, exit 0
- Known failure (bad args, IO, locked DB, unknown categories, ...): `{"ok": false, "error": "...", "type": "...", "details": {...}}` on stderr, exit 1
- Uncaught bug: traceback on stderr, exit 2

## Path conventions

- DB: `$MONOBANK_MCP_DATA_DIR/data.db` or `~/finances/data.db` if the env var is unset. Same env var as the ingest plugins so one setting reroutes everyone.
- Time arguments: unix seconds or ISO 8601 (date or datetime). Naive times treated as UTC.
- Currency arguments: alpha-3 (`UAH`) or ISO numeric (`980`).
- Period arguments: `YYYY-MM`. Validated by regex; any other shape is a hard error.

## Currency semantics

`amount_minor` is always in the **account's** currency. Mono's `transactions.currency_code` is the operation currency (what the merchant charged in); for foreign-merchant rows on a UAH card the two differ. The skill joins to the per-account currency at query time so summaries are denominationally consistent. `op_amount_minor` / `op_currency_code` are still available per row for callers that want the original foreign price.

The user explicitly does not want mixed currencies in totals - every per-currency view stays per-currency, no FX conversion is performed.
