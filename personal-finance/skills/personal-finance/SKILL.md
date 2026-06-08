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

### Enumerate categories in use

```bash
uv run --directory <plugin-root> pf-query categories
```

Returns `{ok, count, categories: [{category, tx_count}]}` sorted by `tx_count` desc. Use this before proposing a new category name (during categorization, or when answering "what taxonomy am I using?") so suggestions stay consistent with the user's existing categories. Resolution: override beats rule-assigned; categories that exist only in rules but have never matched a transaction are not listed (use `pf-rules list` for those).

### Cluster uncategorized transactions

```bash
uv run --directory <plugin-root> pf-query summarize-uncategorized \
  [--group-by description|counterparty|mcc] \
  [--from <date>] [--to <date>] [--bank mono|privat]
```

Returns `buckets: [{key, currency_code, tx_count, total_minor}]` for transactions whose resolved category is NULL. Default grouping is `description`; time bounds are optional (default = all time). Use this in the categorize flow when you need to show the user "here's what needs a rule" without dumping raw rows.

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

A `budget` block appears automatically when the period covers exactly one calendar month AND a budget has been materialised for it. Shape:

```
"budget": {
  "period": "2026-06",
  "blocks": [
    {"currency_code": 980, "status": "active",
     "lines": [{"category": "Їжа/Ресторани",
                "target_minor": -900000, "actual_minor": -423000,
                "delta_minor": 477000, "pct_used": 47.0,
                "in_budget": true}, ...],
     "totals": {"target_minor": ..., "actual_minor": ..., "delta_minor": ...}
    }, ...
  ]
}
```

`in_budget=false` lines are categories you spent on without planning for - surface them prominently in narrative ("you spent 4.5k on Покупки/Інше not in your June plan").

## Budget planning - conversation-driven flow (v0.6.0+)

Since v0.6.0, planning a month is a conversation, not a CSV import. The user says "плануємо <month>"; you drive a structured dialogue, recording each decision as a single CLI call against the shared DB. Sheets are exports, not the editing surface.

### How a planning conversation goes

1. **Start the session.** Call `pf-budget plan start --period YYYY-MM`. Behaviour:
   - If `existing_draft: true`, ask the user: continue / cancel / merge. Do NOT silently continue.
   - Otherwise the draft is created by copying `kind=baseline` lines from the most recent prior active month. `copied_from` is in the response.

2. **Gather suggestions.** Call `pf-budget plan suggest --period YYYY-MM`. This returns history signals - seasonal gaps, monotonic trends, quarterly cadences, one-off deviations, excluded one_time items. Phrase them back as a small batch. Example:
   > Стартую з червневого baseline. Помітив 3 речі:
   > 1. Школа (15 600) - у червні був останній платіж. У липні-серпні зазвичай 0?
   > 2. Зарядка авто в червні була пів місяця через відпустку - повертаємо до 3 000?
   > 3. Готелі (27k) - one-time відпустки, виключаю з шаблону.

3. **Walk through the dialogue.** When the user replies with a number (e.g. "Дружина 18000"), translate to `pf-budget plan update`. When they confirm a batch, apply all those changes. When they introduce a new category, call `pf-budget plan add`. When they say "стоп, поверни X" or "передумав", call `pf-budget plan undo`. When they say "забудь все" or "почнемо спочатку", call `pf-budget plan cancel`.

4. **Multi-currency in one session.** The user can say "додай $300 на ремонт авто" and you call `pf-budget plan add --currency USD ...` on the same period's draft. The CLI creates the USD draft budget on demand. The user thinks of it as one plan.

5. **Confirm and commit.** When the user signals they're done ("Зафіксувати", "Готово"), summarise what's planned, then call `pf-budget plan commit --period YYYY-MM`. The draft replaces any existing active for the same period atomically.

6. **Optional Family export.** Ask "Експортувати для дружини?" Run `pf-budget export --period YYYY-MM --view family --out <path>.xlsx`. Family view has two tabs: `Огляд` (pretty grouped, with SUM formulas) and `Деталі` (full flat list). Do NOT auto-export - only on the user's go-ahead.

### Conversation idioms

- "плануємо липень" → start session
- "так до всього" → apply every batched suggestion
- "Дружина 18000" → update (composite key resolved from context)
- "додай $300 на ремонт авто" → add (one_time)
- "стоп, поверни школу" → undo
- "забудь все" → cancel
- "Зафіксувати" / "Готово" → commit
- "експорт для дружини" → export family

### Subcommand reference

```bash
pf-budget plan start    --period 2026-07 [--copy-from 2026-06]
pf-budget plan suggest  --period 2026-07 [--lookback 6]
pf-budget plan add      --period 2026-07 --category X --currency UAH --kind baseline --amount -9000 [--note]
pf-budget plan update   --period 2026-07 --category X --currency UAH --kind baseline --amount -10000
pf-budget plan remove   --period 2026-07 --category X --currency UAH --kind baseline
pf-budget plan undo     --period 2026-07
pf-budget plan show     --period 2026-07 [--currency UAH]    # shows draft if any, else active
pf-budget plan commit   --period 2026-07
pf-budget plan cancel   --period 2026-07
```

Composite-key addressing (`--category` + `--currency` + `--kind`) must match exactly one line. When multiple match (e.g. several `one_time` hotels in one month), the response includes `candidate_line_ids` in `details`; re-issue with `--line-id <N>`.

### Family export shape

`pf-budget export --period YYYY-MM --view family --out plan.xlsx` produces a styled workbook:

- **Огляд**: per-currency block with navy header total + light-yellow group headers (Житло / Харчування / ...) + indented line rows with banding. Group subtotals and currency totals are SUM formulas, so if the spouse adjusts a number in Sheets the totals recompute.
- **Деталі**: flat table with `Період / Група / Категорія / Валюта / Тип / Сума / Нотатка` for "що це за стаття?".

The Ukrainian renderer maps internal taxonomy keys to display names: `Покупки/Дім` becomes `Покупки → Дім`, `kind=baseline` becomes `звичайне`, etc.

### What NOT to do during a planning conversation

- Do NOT silently register unknown categories - if the user introduces a new category, call `pf-budget register-category` only after explicit confirmation. Once registered, it's in the taxonomy.
- Do NOT auto-commit the draft. The user's explicit "Зафіксувати" is the only trigger.
- Do NOT auto-export. Even after commit, ask before generating the Family XLSX.
- Do NOT mix currencies into a single total in narrative. UAH and USD always stay separate.
- Do NOT bulk-import via `pf-budget import` during a conversation. That subcommand is for one-shot migration from CSV; the conversation path uses `plan add/update/remove` exclusively.

## Other budget commands (v0.5.0+)

### Import a budget from CSV / XLSX

```bash
uv run --directory <plugin-root> pf-budget import <file> --period 2026-06 \
  [--unknown-categories reject|register] \
  [--dry-run] [--force] [--sheet plans|baseline]
```

- CSV defaults to the Plans-shape: `Period, Category, Currency, Kind, Amount, Note`.
- XLSX is read as a two-sheet workbook: `Baseline` + `Plans`; merge happens automatically (Plans rows for `--period` override Baseline rows for the same `(category, currency, kind)`).
- `--unknown-categories reject` (default) fails with structured payload: each unknown gets up to 3 Levenshtein-closest known categories so the user sees probable typos vs legitimate new categories.
- `--unknown-categories register` adds every unknown to `category_registry` with `declared_via=budget-import` and proceeds.
- `--dry-run` validates without writing (no budget rows, no registry rows, no audit log).
- `--force` overwrites a `status=closed` budget. Rare. Tell the user before doing this.

The unknown-category JSON shape (use it to render a useful prompt back to the user):

```
{"ok": false, "error": "...", "type": "UnknownCategories",
 "details": {"unknown": [
    {"category": "Підиски/AI",
     "suggestions": [{"candidate": "Підписки/AI", "distance": 1}, ...]
    }, ...
 ]}}
```

### Inspect a materialised budget

```bash
pf-budget show --period 2026-06 [--currency UAH]
pf-budget list                  # all budgets, status, totals
```

### Compare budget vs actuals

```bash
pf-budget diff --period 2026-06 [--currency UAH]
```

Joins budget lines with actuals via the same category-resolution path as `pf-query`. Categories that exist only in actuals (no budget line) surface as `in_budget=false`. Excludes `Перекази/СвоїКартки` by default to match the "real spending" convention.

### Snapshot / reopen / delete

```bash
pf-budget close  --period 2026-05  [--currency UAH]
pf-budget reopen --period 2026-05  [--currency UAH] [--reason "..."]
pf-budget delete --period 2026-04  [--currency UAH] [--force]
```

Closing flips `status='closed'`; subsequent `pf-budget import` for the period refuses without `--force`. `budget_line` mutations on closed budgets are blocked at the trigger level too. Reopen restores `status='active'`.

### Rename a category across tables

```bash
pf-budget rename-category --from 'Покупки/Дім' --to 'Покупки/Будинок' \
                          --update budget_line,tx_category,categorization_rules,category_overrides,category_registry
```

`--update` is a comma-separated subset of allowed tables. Atomic per call. Rename will fail if it would touch a `budget_line` row whose parent budget is closed - reopen first.

### Export variance to spreadsheet

```bash
pf-budget export --period 2026-06 --out variance.csv  [--currency UAH]
pf-budget export --period 2026-06 --out variance.xlsx --format auto
```

CSV uses stdlib; XLSX requires the `sheets` optional dependency (install via `uv pip install pf-skill[sheets]`).

### Manage the category registry

```bash
pf-budget register-category   --category 'Покупки/Сад' [--note "Дача"]
pf-budget unregister-category --category 'Покупки/Сад' [--force]
pf-budget list-categories     [--include-declared]
```

The registry is the explicit "this category exists" contract. `register-category` is idempotent. `unregister-category` refuses when the category is referenced in `tx_category` / `category_overrides` / `categorization_rules` / `budget_line` (use `--force` only after cleaning up the references).

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
- Do NOT delete or move source data files. The query / report paths are read-only; only the budget / rules / categorize paths mutate the `pf_*` and `budget*` tables, and they own only those.
- Do NOT call `pf-budget import` with `--unknown-categories register` silently. If the user did not approve adding new categories to the registry, run with the default `reject` mode first, show the Levenshtein suggestions, and ask before re-running with `register`. Typos look identical to legitimate new categories in the input - the user is the only one who can tell them apart.
