# Example workflow

End-to-end from "I just exported a statement" to "data is in `~/finances/data.db`".

```text
1. User: opens https://next.privat24.ua/wallet
   - clicks the card to export from the left list
   - stays on the "Історія" tab
   - optionally sets a date range via "Період" (wider = safer; we
     dedupe by natural key, so overlapping re-exports don't duplicate)
   - clicks the "Експорт у XLS" icon (Excel-style grey sheet,
     between the search field and the "Фільтр" button)
   - downloads e.g. "vyp_05_2026.xlsx"
   - drops the file into ~/finances/inbox/

2. User (in Claude Code): "import privat"

3. Skill runs:
   $ uv run --directory $CLAUDE_PLUGIN_ROOT privat24-import import-inbox

   Output:
   [
     {
       "file": "~/finances/inbox/vyp_05_2026.xlsx",
       "status": "imported",
       "rows_inserted": 112,
       "rows_skipped": 0,
       "import_run_id": 3,
       "archived_to": "~/finances/archive/2026-05-21/vyp_05_2026.xlsx"
     }
   ]

4. Claude reports: "Imported 112 transactions. File archived to ~/finances/archive/2026-05-21/."

5. User (in a follow-up): "import privat" (rerun by mistake)

6. Skill output:
   {"status": "skipped", ...}

   Claude reports: "Already imported in run #3; nothing new."
```

Cross-bank queries / category reports happen via the personal-finance plugin; this skill stays in its lane and only touches `privat_*` tables.
