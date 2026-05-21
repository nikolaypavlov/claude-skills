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

1. Install the plugin (via `/plugin install` or marketplace UI).
2. Export your statement from <https://privat24.ua/statement>:
   - pick the card and date range
   - choose **Excel** as the file format
   - save the downloaded `vyp*.xlsx` (or similarly-named file)
3. Drop it into `~/finances/inbox/` (the directory is auto-created on first run).
4. Tell Claude "import privat" (or your file name). The skill picks it up.

## What the importer does

- **SHA-based short-circuit**: re-importing the same byte sequence returns `status: skipped`; the file is not re-parsed.
- **Natural-key dedup**: a stable id is derived from (`ts`, `amount`, `description`, `account_id`). Re-exporting an overlapping date range from privat24.ua does NOT create duplicate rows.
- **Twin-row tie-break**: if two rows share the full natural key (e.g. an auto-payment executed twice within one second), an in-file counter keeps their ids distinct.
- **FX accounting**: when the operation currency differs from the account currency, both `op_amount_minor` and `op_currency_code` are populated with the sign mirrored from the account amount. Same-currency rows leave both columns NULL (matches the monobank-mcp convention).
- **Idempotent migrations**: schema is applied inside an explicit `BEGIN`/`COMMIT`. A kill mid-migration rolls back cleanly.
- **File archival**: on success the source moves to `~/finances/archive/YYYY-MM-DD/`. Pass `--no-archive` to keep the source in place.

## Schema

See [`schema/privat_001_initial.sql`](./schema/privat_001_initial.sql). All tables are prefixed `privat_`:

- `privat_accounts` - one row per card, derived from the masked PAN in the XLSX.
- `privat_transactions` - one row per statement entry; conforms to `docs/transactions-schema.md` (cross-plugin contract).
- `privat_import_runs` - audit log; `file_sha256` indexed for fast short-circuit.
- `privat_schema_version` - migration tracker.

## Standalone use

The plugin works without `monobank-mcp` or `personal-finance` installed. Imports run independently and the `privat_*` tables are created on first connect. Cross-bank queries / categorisation are added by the umbrella `personal-finance` plugin (PR#3 in the design).

## CLI

```bash
# Single file
uv run privat24-import import ~/finances/inbox/vyp.xlsx

# Every XLSX in the inbox
uv run privat24-import import-inbox

# Skip the archive move (e.g. for one-off inspection)
uv run privat24-import import ~/path/to/file.xlsx --no-archive
```

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
