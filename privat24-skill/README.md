# privat24-skill

Standalone Claude Code skill that imports Privat24 web-cabinet statement exports (XLSX) into the shared `~/finances/data.db` SQLite store. Owns the `privat_*` schema group; reads nothing else.

This is one of three plugins in the personal-finance design (`docs/personal-finance-design.md`):

```
+-------------------+  +------------------+  +---------------------------+
|  monobank-mcp     |  | privat24-skill   |  |    personal-finance       |
|  (Rust, owns      |  | (Python, owns    |  |    (Python MCP, owns      |
|   mono_*)         |  |  privat_*)       |  |    pf_*, reads both)      |
+--------+----------+  +---------+--------+  +-------------+-------------+
         |                       |                          |
         v                       v                          v
+------------------------------------------------------------------------+
|                  ~/finances/data.db  (SQLite, WAL)                     |
+------------------------------------------------------------------------+
```

## Quick start

1. Make sure [uv](https://docs.astral.sh/uv/) is installed (`brew install uv` or the official installer). The skill ships as a Python package and `uv run` manages its virtualenv.
2. Install the plugin (via `/plugin install privat24-skill@ai-engineering-skills` or marketplace UI).
3. Export the XLSX statement from Privat24 (see [Exporting a statement](#exporting-a-statement) below).
4. Drop it into `~/finances/inbox/` (the directory is auto-created on first run).
5. Tell Claude "import privat" (or mention the file name). The skill picks it up and runs `privat24-import import-inbox`.

## Exporting a statement

1. Log in at <https://privat24.ua/> in any browser.
2. Open **"Гаманець"** (Wallet).
3. Click the card you want to export from the left-hand list.
4. On the right pane stay on the **"Історія"** (History) tab.
5. Optionally set a date range via the **"Період"** picker. Wider ranges
   are fine - the importer dedupes by natural key so overlapping
   re-exports do not create duplicate rows.
6. Click the small **document icon** (sheet with a download arrow)
   between the search field and the **"Фільтр"** button, then choose
   **Excel** in the pop-up.
7. Save the downloaded file (Privat24 names it something like
   `vyp_<date_range>.xlsx`).

Repeat per card - each XLSX covers exactly one card.

## What the importer does

- **SHA-based short-circuit**: re-importing the same byte sequence returns `status: skipped`; the file is not re-parsed.
- **Natural-key dedup**: a stable id is derived from (`ts`, `amount`, `description`, `account_id`). Re-exporting an overlapping date range from privat24.ua does NOT create duplicate rows.
- **Twin-row tie-break**: if two rows share the full natural key (e.g. an auto-payment executed twice within one second), an in-file counter keeps their ids distinct.
- **FX accounting**: when the operation currency differs from the account currency, both `op_amount_minor` and `op_currency_code` are populated with the sign mirrored from the account amount. Same-currency rows leave both columns NULL (matches the monobank-mcp convention).
- **Idempotent migrations**: schema is applied inside an explicit `BEGIN`/`COMMIT`. A kill mid-migration rolls back cleanly.
- **File archival**: on success the source moves to `~/finances/archive/YYYY-MM-DD/`. Pass `--no-archive` to keep the source in place.

## Schema

See [`src/privat24_import/schema/privat_001_initial.sql`](./src/privat24_import/schema/privat_001_initial.sql). The SQL travels with the Python package (loaded via `importlib.resources`) so it works in both source-tree and wheel layouts. All tables are prefixed `privat_`:

- `privat_accounts` - one row per card, derived from the masked PAN in the XLSX.
- `privat_transactions` - one row per statement entry; conforms to `docs/transactions-schema.md` (cross-plugin contract).
- `privat_import_runs` - audit log; `file_sha256` indexed for fast short-circuit.
- `privat_schema_version` - migration tracker.

The migration runs inside a single explicit `BEGIN`/`COMMIT` (no `executescript` - it auto-commits before the script runs and would defeat the envelope). A crash mid-apply rolls back every DDL including the version-tracker table.

## Timezone handling

Privat24 web exports stamp every row with naive Europe/Kyiv local time. The parser attaches `ZoneInfo("Europe/Kyiv")` so the stored unix timestamp is true UTC seconds. The `tzdata` PyPI package is pinned as a runtime dependency so `ZoneInfo` works on systems without an IANA tz database (Windows by default, some slim Linux container images).

## Standalone use

The plugin works without `monobank-mcp` or `personal-finance` installed. Imports run independently and the `privat_*` tables are created on first connect. Cross-bank queries / categorisation are added by the umbrella `personal-finance` plugin (PR#3 in the design).

## CLI

The CLI is invoked through `uv run`, which manages the virtualenv. The
`--directory` flag points uv at the plugin's `pyproject.toml` so the
commands work from any cwd:

```bash
# Single file
uv run --directory <path-to-privat24-skill> \
  privat24-import import ~/finances/inbox/vyp.xlsx

# Every XLSX in the inbox
uv run --directory <path-to-privat24-skill> privat24-import import-inbox

# Skip the archive move (e.g. for one-off inspection)
uv run --directory <path-to-privat24-skill> \
  privat24-import import ~/path/to/file.xlsx --no-archive
```

If you've `cd`'d into `privat24-skill/` you can drop `--directory`.
Inside Claude Code the skill uses `${CLAUDE_PLUGIN_ROOT}` instead - see
`skills/privat24-import/SKILL.md`.

The JSON output is intended to be piped or parsed. Exit codes:

- `0` for `imported` or `skipped`
- `1` for `unsupported`, `error`, or any I/O failure

## Development

```bash
cd privat24-skill
uv sync
uv run pytest -q
uv run python fixtures/generate.py   # regenerate sample_web.xlsx
```

All fixtures are seeded (`fixtures/generate.py` uses a fixed RNG) and contain only generic merchant names + masked test PANs. Never edit `fixtures/sample_web.xlsx` by hand - regenerate via the script.
