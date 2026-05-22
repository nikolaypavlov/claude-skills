---
name: personal-finance
description: |
  Use this skill when the user asks for a financial report, spending
  summary, category breakdown, or transaction lookup over their personal
  finance data combined across Monobank and Privat24. Triggers in any
  of the following shapes (Ukrainian or English):
  - "звіт за <період>", "report for <month>", "spending report"
  - "скільки я витратив", "how much did I spend"
  - "покажи транзакції", "list transactions", "show transactions"
  - "розбий витрати по категоріях", "spending by category"
  - "знайди транзакцію", "find transaction", "пошук по описам"
  - "list accounts", "які в мене рахунки"
  Reads ~/finances/data.db; needs monobank-mcp (for inline incremental
  sync before reports) and at least one ingest plugin installed.
allowed-tools: Bash, Read
---

# Personal finance: query, report, categorize

## Pre-flight before any report or summary

1. Call the MCP tool `mcp__monobank__ensure_synced` with `max_wait_seconds=90` so Mono data is fresh. If the response includes `partial: true`, tell the user up-front ("Mono sync вийшов partial, можу продовжити з тим що є або зачекати - як зручніше?") and let them choose before continuing.
2. Privat24 has no API. Do NOT try to sync it - the user uploads XLSX exports manually via privat24-skill. Reports use whatever Privat data is already in the store; if `last_sync_ts.privat` in the report bundle looks stale, mention it but do not auto-import.

The pre-flight does NOT apply to "find a transaction" lookups or "list my accounts" - those are cheap and we don't want to add 60-90s of latency for a one-line answer.

## Invocation form

Entry points are exposed as `[project.scripts]` in the plugin's `pyproject.toml`. Invoke them via `uv run --directory <plugin-root> pf-query ...` / `uv run --directory <plugin-root> pf-report ...`. `<plugin-root>` is wherever the plugin was installed (typically under `~/.claude/plugins/cache/<marketplace>/personal-finance/<version>/`). uv handles the project's venv (`uv sync` on first call as needed).

## Tool invocations (all read-only in PR#3 scope)

### List accounts across all banks

```bash
uv run --directory <plugin-root> pf-query accounts
```

Returns `{ok, detected_banks, accounts: [{bank, account_id, label, currency_code, ...}]}`. If no ingest plugin has populated tables, you'll see `warning: "no transaction sources detected..."` - tell the user which plugins to install.

### Filtered transaction list

```bash
uv run --directory <plugin-root> pf-query list \
  --from 2026-04-01 --to 2026-05-01 \
  [--bank mono|privat] [--account <id>] [--category Food] \
  [--currency UAH] [--limit 500] [--offset 0]
```

`--from` / `--to` accept either unix seconds or ISO 8601 (date or datetime). Times without an explicit timezone are treated as UTC. `--currency` accepts the alpha-3 (`UAH`, `USD`, `EUR`, `GBP`) or the ISO numeric (`980`, ...).

### Aggregate by a dimension

```bash
uv run --directory <plugin-root> pf-query summarize \
  --from 2026-04-01 --to 2026-05-01 \
  --group-by category    # or: mcc | counterparty | currency | account | bank
  [--bank mono] [--currency UAH]
```

Returns `buckets: [{key, currency_code, total_minor, tx_count}]` sorted by `total_minor` ascending (so the biggest outflows appear first - signed minor units).

### Substring search

```bash
uv run --directory <plugin-root> pf-query find --query "GLOVO" [--limit 100]
```

Case-insensitive LIKE over `description` and `counterparty`.

### Full report bundle (for narrative reports)

```bash
uv run --directory <plugin-root> pf-report \
  --from 2026-04-01 --to 2026-05-01 \
  [--comparison previous-period] \
  [--account <id>] [--bank mono|privat]
```

Returns a structured bundle with:
- `period`, `accounts`, `currencies_seen`
- `transactions[]` for periods up to 90 days; `monthly_buckets[]` + `top_transactions[]` (largest by absolute amount) for longer periods
- `uncategorized_transactions[]` always (so you can prompt the user to add rules)
- `active_rules_count`, `uncategorized_count`
- `last_sync_ts: {mono: ts, privat: ts}` - check this before composing the narrative; warn the user if Mono is more than a day stale or Privat is more than a month stale

The `comparison` block (when requested) gives `per_currency.current` vs `per_currency.previous` for a symmetrical window immediately before `--from`.

## Output contract

- Success: JSON payload on stdout, exit 0. Parse it directly.
- Validation / IO / permission error: stderr line is `{"ok": false, "error": "...", "type": "..."}`, exit 1. Read it and explain in plain language.
- Uncaught crash: traceback on stderr, exit 2. Tell the user and stop - do NOT retry blindly.

## Narrative report structure (when user asks for a report)

After calling `pf-report` and getting the bundle, compose the narrative roughly in this order:

1. Header: period, accounts touched, currencies seen, sync-freshness warning if any.
2. Per-currency summary: total in / out / net / tx_count, vs previous period if `comparison` is present.
3. Category breakdown per currency, sorted desc, with `%` of total outflow.
4. Top counterparties (top 5-10).
5. Recurring: monthly-cadence outflows that show up across multiple `year_month` buckets in similar amounts.
6. Anomalies: outsized transactions vs the typical bucket size, new merchants in big categories.
7. Uncategorized review: walk through `uncategorized_transactions[]`, suggest a category, ask the user to confirm. (Mutation commands land in PR#4.)
8. Insights: free-form prose.

Never invent numbers. If the bundle is empty or partial, say so.

## What NOT to do

- Do NOT write raw SQL against `~/finances/data.db`. Always go through the `pf-*` scripts so the cross-bank UNION discovery stays consistent.
- Do NOT touch `mono_*` or `privat_*` tables directly. They are owned by their ingest plugins.
- Do NOT mix currencies into a single total. Report per-currency. The user's design choice.
- Do NOT auto-categorize or auto-add rules in PR#3 scope - those commands arrive in PR#4. For now, list the uncategorized transactions and explain that the user will need to categorize them once PR#4 lands.
- Do NOT delete or move source data files. This skill is read-only.
