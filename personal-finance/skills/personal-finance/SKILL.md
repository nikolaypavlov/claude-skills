---
name: personal-finance
description: |
  Use this skill when the user asks about cross-bank personal finance
  queries over the shared ~/finances/data.db SQLite store - "show me
  transactions", "how much did I spend", "list my accounts", "summarize
  spending", "розбий по категоріях", "звіт за місяць", "скільки я витратив",
  "покажи перекази", "перекажу скільки залишилось". The skill operates
  through the `personal-finance` MCP server which auto-discovers the
  installed ingest plugins (mono_*, privat_*) and projects them to a
  common Transaction shape via UNION ALL.
allowed-tools: ["mcp__personal_finance__*", "Bash", "Read"]
---

# Personal Finance umbrella

Cross-bank queries over the shared `~/finances/data.db`. Auto-discovers
`<bank>_transactions` tables produced by ingest plugins
(`monobank-mcp`, `privat24-skill`) and projects them through a runtime
UNION ALL.

## When invoked

User asks any of:

- "list my accounts", "які в мене рахунки"
- "show me transactions in <period>", "покажи витрати за <період>"
- "how much did I spend on <category>", "скільки на <категорію>"
- "summarize spending by <category|mcc|counterparty|currency|account|bank>"

If `mcp__personal_finance__data_sources` reports `detected_banks: []`,
tell the user no ingest plugin has populated the store yet and point
them at `/monobank-mcp:setup` or the `privat24-import` workflow.

## What's available right now (0.1.0)

| Tool                  | Purpose |
|-----------------------|---------|
| `data_sources`        | Diagnostic: which ingest plugins are visible, pf_* schema version. |
| `list_accounts`       | Every account across every installed ingest. |
| `get_transactions`    | Filterable, paginated cross-bank query. Resolves category (override > rule > NULL). |
| `summarize_spending`  | Aggregate by category/mcc/counterparty/currency/account/bank. Per-currency totals - never auto-converts. |

PR#4 adds: `find_transaction`, `get_report_bundle`, `set_category`,
`add_rule` (preview-only), `reload_rules`, `apply_rules_retroactively`,
`categorize_uncategorized`, plus the `/personal-finance:categorize`
command.

## Steps

1. Probe with `data_sources` first if you don't already know what's in
   the store. Surface any warning to the user verbatim.
2. For "list accounts" requests call `list_accounts`. Group by bank in
   the reply so the user sees mono cards next to privat cards.
3. For "show transactions" requests:
   - Convert relative dates ("last week", "квітень") to unix seconds
     in Europe/Kyiv tz BEFORE calling the tool. Pass them as
     `from_ts` / `to_ts`.
   - If the user named a specific account/bank/category, pass it in
     the corresponding filter. Don't post-filter in chat.
   - Default `limit` is 500. Bump to 5000 only if the user asks for a
     wide sweep.
4. For "summarize spending" requests choose a sensible `group_by`:
   - "by category" -> `category` (NULLs surface as `(uncategorized)`)
   - "by мерчанту" / "by counterparty" -> `counterparty`
   - "by card" -> `account`
   - default to `category`
   - Show separate totals per currency in the reply - multi-currency
     accounts are common.
5. Format numbers as decimal UAH/USD/EUR (`amount_minor / 100`) when
   talking to the user; the tool returns signed minor units.

## What NOT to do

- Do NOT write to `pf_*` tables yet - the write-path tools
  (`set_category`, `add_rule`, ...) ship in PR#4 and currently raise.
- Do NOT touch `mono_*` or `privat_*` tables. The umbrella reads
  through the projection only; ingest is owned by the ingest plugins.
- Do NOT convert across currencies. Per-currency reporting is by
  design - exchange-rate noise is worse than the alternative.

## Verifying setup

After install ask Claude to run `data_sources`. Expected for a working
setup:

```json
{
  "detected_banks": ["mono", "privat"],
  "pf_schema_version": 1,
  "db_path": "/Users/.../finances/data.db",
  "warning": null
}
```

If `detected_banks` is empty:

- Run `/monobank-mcp:setup` + `monobank-mcp backfill --from <date>` for
  Monobank.
- Drop a Privat24 XLSX into `~/finances/inbox/` and ask Claude
  "import privat".
