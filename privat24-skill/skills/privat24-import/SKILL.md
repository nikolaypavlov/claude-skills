---
name: privat24-import
description: Import a Privat24 statement export (XLSX from privat24.ua) into the shared ~/finances/data.db SQLite store. Triggers - user says "import privat", "залий приват", "оновити приват", "імпортуй CSV з привату", "оновити виписку privat24", or mentions a file named "privat*.xlsx" / "Виписки*.xlsx" / "vyp*.xlsx".
allowed-tools: Bash, Read, Glob, Write
---

# Privat24 statement import

This skill imports Privat24 web-cabinet statement exports (XLSX) into the shared `~/finances/data.db` SQLite store. It owns the `privat_*` tables and writes nothing else.

## When invoked

The user just exported a statement from Privat24 and dropped it (or several) into `~/finances/inbox/`, OR pointed at a specific file path.

If they don't yet have an XLSX on disk and ask how to get one: open <https://next.privat24.ua/wallet>, click the card, stay on the **Історія** tab, click the **"Експорт у XLS"** icon (Excel-style grey sheet) between the search field and the **Фільтр** button, save the resulting file. Each XLSX covers exactly one card.

## Steps

1. **Locate the data directory**. If `$MONOBANK_MCP_DATA_DIR` is set in the user's env, use that. Otherwise default to `~/finances`.

2. **Discover the candidate file(s)**:
   - If the user named a specific path, use it.
   - Otherwise list `~/finances/inbox/*.xlsx`. If multiple match, ask the user to confirm or pass `--all` to import every one.

3. **Run the importer**. From this plugin's directory (`${CLAUDE_PLUGIN_ROOT}` resolves to it). Use `set -e` so Bash propagates a `uv run` startup failure (missing venv, broken install) instead of leaving Claude to parse empty stdout as JSON:

   ```bash
   set -e
   uv run --directory "${CLAUDE_PLUGIN_ROOT}" privat24-import import "<path>"
   ```

   Or for batch:

   ```bash
   set -e
   uv run --directory "${CLAUDE_PLUGIN_ROOT}" privat24-import import-inbox
   ```

   The command:
   - Computes the file SHA-256. If `privat_import_runs` already has a row with that SHA, the import is short-circuited as `status: skipped` - no re-parse, no duplicates.
   - Otherwise detects the file format. Today only the web-cabinet XLSX is recognised; mobile / FOP variants land as `status: unsupported` until parsers are added.
   - Parses every data row, derives a stable `privat_h_<hash>` id from the natural key (timestamp + amount + description + account), and inserts via `INSERT OR IGNORE` so re-importing overlapping date ranges from different XLSXs deduplicates correctly.
   - Logs the run in `privat_import_runs` (started_at / finished_at / counts / file_sha256).
   - Moves the source file to `~/finances/archive/YYYY-MM-DD/` on success (suppress with `--no-archive`).

4. **Report to the user**. The CLI emits a single JSON object (or array for `import-inbox`). Translate the relevant fields:
   - `status: imported`: "Imported N rows from <file>; archived to <archived_to>."
   - `status: skipped`: "<file> already imported in run <id>; no changes."
   - `status: unsupported`: show the `error` reason and ask the user to share a redacted sample so we can extend `parsers/detect.py`.
   - `status: error`: surface the error message and DO NOT delete the source file.

## What NOT to do

- Do NOT categorise transactions - that is the personal-finance plugin's job (`pf_*` tables).
- Do NOT touch `mono_*` or `pf_*` tables. Stay inside `privat_*`.
- Do NOT delete the source file. The CLI moves to archive on success; on failure leave the file in place for the user to re-try.
- Do NOT inline the user's masked PAN, balances, or descriptions in chat unless the user explicitly asks. The skill operates over the file on disk.
- Do NOT run this skill if `~/finances/data.db` is on shared / cloud storage and another user might also be writing - WAL is enabled but cross-machine concurrent writes still corrupt SQLite.

## Verifying

After import, the user can verify with any SQLite client:

```bash
python3 -c "
import sqlite3, sys
c = sqlite3.connect('~/finances/data.db'.replace('~', '$HOME'))
print('transactions:', c.execute('SELECT COUNT(*) FROM privat_transactions').fetchone()[0])
for r in c.execute('SELECT account_id, COUNT(*) FROM privat_transactions GROUP BY account_id'):
    print(' ', r)
"
```

For real cross-bank queries / categorisation, the personal-finance plugin (PR#3 in the design doc) is the entry point.
