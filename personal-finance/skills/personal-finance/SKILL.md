---
name: personal-finance
description: |
  Use this skill when the user asks for a financial report, spending
  summary, category breakdown, budget plan, or transaction lookup
  over their personal finance data combined across Monobank and
  Privat24. Triggers in any of the following shapes (Ukrainian or
  English):
  - "звіт за <період>", "report for <month>", "spending report"
  - "скільки я витратив", "how much did I spend"
  - "покажи транзакції", "list transactions", "show transactions"
  - "розбий витрати по категоріях", "spending by category"
  - "знайди транзакцію", "find transaction", "пошук по описам"
  - "list accounts", "які в мене рахунки"
  - "плануємо <місяць>", "plan <month>", "як я по бюджету"
  Reads ~/finances/data.db; needs monobank-mcp (for inline incremental
  sync before reports) and at least one ingest plugin installed.
allowed-tools: Bash, Read
---

# Personal finance: query, report, categorize, budget

## Pre-flight before any report or summary

1. Call the MCP tool `mcp__monobank__ensure_synced` with `max_wait_seconds=90` so Mono data is fresh. If the response includes `partial: true`, tell the user up-front ("Mono sync вийшов partial, можу продовжити з тим що є або зачекати - як зручніше?") and let them choose before continuing.
2. Privat24 has no API. Do NOT try to sync it - the user uploads XLSX exports manually via privat24-skill. Reports use whatever Privat data is already in the store; if `last_sync_ts.privat` in the report bundle looks stale, mention it but do not auto-import.

The pre-flight does NOT apply to "find a transaction" lookups, "list my accounts", budget planning, or any `pf-budget plan` operation - those are local and we don't want to add 60-90s of latency for a one-line answer.

## Invocation form

Entry points are exposed as `[project.scripts]` in the plugin's `pyproject.toml`. Invoke them via `uv run --directory <plugin-root> pf-query ...` / `uv run --directory <plugin-root> pf-report ...` / etc. `<plugin-root>` is wherever the plugin was installed (typically under `~/.claude/plugins/cache/<marketplace>/personal-finance/<version>/`). uv handles the project's venv (`uv sync` on first call as needed).

## Read commands

### List accounts across all banks

```bash
pf-query accounts
```

Returns `{ok, detected_banks, accounts: [{bank, account_id, label, currency_code, ...}]}`. If no ingest plugin has populated tables, you'll see `warning: "no transaction sources detected..."` - tell the user which plugins to install.

### Filtered transaction list

```bash
pf-query list \
  --from 2026-04-01 --to 2026-05-01 \
  [--bank mono|privat] [--account <id>] [--category Food] \
  [--currency UAH] [--limit 500] [--offset 0]
```

`--from` / `--to` accept either unix seconds or ISO 8601 (date or datetime). Times without an explicit timezone are treated as UTC. `--currency` accepts the alpha-3 (`UAH`, `USD`, `EUR`, `GBP`) or the ISO numeric (`980`, ...).

### Aggregate by a dimension

```bash
pf-query summarize \
  --from 2026-04-01 --to 2026-05-01 \
  --group-by category    # or: mcc | counterparty | currency | account | bank
  [--bank mono] [--currency UAH]
```

Returns `buckets: [{key, currency_code, total_minor, tx_count}]` sorted by `total_minor` ascending (so the biggest outflows appear first - signed minor units). The `currency_code` is the ACCOUNT's currency, not the operation currency - cross-border purchases (e.g. Patreon on a UAH card) are denominated in the card's currency.

### Substring search

```bash
pf-query find --query "GLOVO" [--limit 100]
```

Case-insensitive LIKE over `description` and `counterparty`.

### Enumerate categories in use

```bash
pf-query categories [--include-declared]
```

Returns `{ok, count, categories: [{category, tx_count, declared}]}` sorted by `tx_count` desc. With `--include-declared`, categories from `category_registry` that have no matching transactions yet are surfaced with `tx_count: 0, declared: true`. Use this before proposing a new category name so suggestions stay consistent with the user's existing taxonomy.

### Cluster uncategorized transactions

```bash
pf-query summarize-uncategorized \
  [--group-by description|counterparty|mcc] \
  [--from <date>] [--to <date>] [--bank mono|privat]
```

Returns `buckets: [{key, currency_code, tx_count, total_minor}]` for transactions whose resolved category is NULL. Default grouping is `description`; time bounds are optional (default = all time). Use this in the categorize flow when you need to show the user "here's what needs a rule" without dumping raw rows.

### Full report bundle (narrative reports)

```bash
pf-report \
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

A `budget` block appears automatically when the period covers exactly one calendar month AND an active budget has been materialised for it:

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

## Budget planning (conversation-driven)

Planning a month is a conversation, not a CSV import. The user says "плануємо <month>"; you drive a structured dialogue, recording each decision as a single CLI call against the shared DB. Sheets are exports, not the editing surface.

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

6. **Optional Family export.** Ask "Експортувати для дружини?" Run `pf-budget export --period YYYY-MM --view family --out <path>.xlsx`. Family view has two tabs: `Огляд` (pretty grouped, with SUM formulas so spouse-side edits live-recompute) and `Деталі` (full flat list). Do NOT auto-export - only on the user's go-ahead.

### Conversation idioms

| User says | Subcommand |
|---|---|
| "плануємо липень" | `plan start --period 2026-07` |
| "так до всього" | apply every batched suggestion |
| "Дружина 18000" | `plan update` (composite key) |
| "додай $300 на ремонт авто" | `plan add --currency USD --kind one_time` |
| "стоп, поверни школу" | `plan undo` |
| "забудь все" | `plan cancel` |
| "Зафіксувати" / "Готово" | `plan commit` |
| "експорт для дружини" | `export --view family` |

### Planning subcommand reference

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

- **Огляд**: per-currency block with navy header total + light-yellow group headers (Житло / Харчування / Транспорт / Підписки / ...) + indented line rows with banding. Group subtotals and currency totals are SUM formulas, so if the spouse adjusts a number in Sheets the totals recompute.
- **Деталі**: flat table with `Період / Група / Категорія / Валюта / Тип / Сума / Нотатка` for "що це за стаття?".

The Ukrainian renderer maps internal taxonomy keys to display names: `Покупки/Дім` becomes `Покупки → Дім`, `kind=baseline` becomes `звичайне`, etc.

## Budget read and lifecycle commands

These are non-planning operations - inspecting, comparing, closing, renaming. Safe to call without an active conversation.

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

Closing flips `status='closed'`; `budget_line` mutations on closed budgets are blocked at the trigger level. Reopen restores `status='active'`. Delete refuses closed budgets without `--force`.

### Rename a category across tables

```bash
pf-budget rename-category --from 'Покупки/Дім' --to 'Покупки/Будинок' \
                          --update budget_line,tx_category,categorization_rules,category_overrides,category_registry
```

`--update` is a comma-separated subset of allowed tables. Atomic per call. Rename fails if it would touch a `budget_line` row whose parent budget is closed - reopen first.

### Export views

```bash
pf-budget export --period 2026-06 --out variance.csv                       # default: variance
pf-budget export --period 2026-06 --out plan.xlsx     --view plan
pf-budget export --period 2026-06 --out family.xlsx   --view family        # XLSX only
```

CSV uses stdlib; XLSX requires the `sheets` optional dependency (install via `uv pip install pf-skill[sheets]`).

### Manage the category registry

```bash
pf-budget register-category   --category 'Покупки/Сад' [--note "Дача"]
pf-budget unregister-category --category 'Покупки/Сад' [--force]
pf-budget list-categories     [--include-declared]
```

The registry is the explicit "this category exists" contract. `register-category` is idempotent. `unregister-category` refuses when the category is referenced in `tx_category` / `category_overrides` / `categorization_rules` / `budget_line` (use `--force` only after cleaning up the references).

### Bulk CSV/XLSX import (side door)

`pf-budget import` exists as a one-shot bulk loader - useful when migrating a plan from elsewhere or restoring from a CSV. The conversation path uses `plan add/update/remove` exclusively; do not reach for `import` mid-dialogue.

```bash
pf-budget import <file> --period 2026-06 \
  [--unknown-categories reject|register] \
  [--dry-run] [--force] [--sheet plans|baseline]
```

Unknown-category JSON shape (use to render typo suggestions back to the user):

```
{"ok": false, "error": "...", "type": "UnknownCategories",
 "details": {"unknown": [
    {"category": "Підиски/AI",
     "suggestions": [{"candidate": "Підписки/AI", "distance": 1}, ...]
    }, ...
 ]}}
```

## Categorization commands

`pf-categorize` runs the rule pass over uncategorized transactions; `pf-rules` manages the rule table directly.

```bash
pf-categorize --scope all|last-n-days [--n 30]

pf-rules add --match-field description|counterparty|mcc \
             --pattern "..." --category "Their/Name" \
             [--priority N] [--source S] [--apply]

pf-rules apply        --rule-id N [--dry-run]
pf-rules set-category --tx-id ID --category C
pf-rules set-override --tx-id ID --category C [--note T]
pf-rules list         [--enabled-only] [--source S]
```

Rule priority is lower-wins: seed rules sit at 200-300; user rules need priority `< 100` to override (use 10-20 for clear intent). `pf-rules add --apply` only backfills uncategorized rows - to remap rows already pinned to an old category, use `pf-rules set-category --tx-id <id>`.

## Output contract

- Success: JSON payload on stdout, exit 0. Parse it directly.
- Known failure (bad args, IO, locked DB, unknown categories, ...): single-line JSON on stderr - `{"ok": false, "error": "...", "type": "...", "details": {...}}`, exit 1. Read it and explain in plain language.
- Uncaught crash: traceback on stderr, exit 2. Tell the user and stop - do NOT retry blindly.

## Narrative report structure (when user asks for a report)

After calling `pf-report` and getting the bundle, compose the narrative roughly in this order:

1. Header: period, accounts touched, currencies seen, sync-freshness warning if any.
2. Per-currency summary: total in / out / net / tx_count, vs previous period if `comparison` is present.
3. Category breakdown per currency, sorted desc, with `%` of total outflow.
4. Top counterparties (top 5-10).
5. Recurring: monthly-cadence outflows that show up across multiple `year_month` buckets in similar amounts.
6. Anomalies: outsized transactions vs the typical bucket size, new merchants in big categories.
7. Budget vs actuals: when the period covers one calendar month and a `budget` block is present, surface overspending and any `in_budget=false` rows.
8. Uncategorized review: walk through `uncategorized_transactions[]`, propose categories, ask the user to confirm before adding rules.
9. Insights: free-form prose.

Never invent numbers. If the bundle is empty or partial, say so.

## What NOT to do

- Do NOT write raw SQL against `~/finances/data.db`. Always go through the `pf-*` scripts so the cross-bank UNION discovery stays consistent.
- Do NOT touch `mono_*` or `privat_*` tables directly. They are owned by their ingest plugins.
- Do NOT mix currencies into a single total in narrative. Report per-currency.
- Do NOT auto-commit a budget draft. The user's explicit "Зафіксувати" / "Готово" is the only trigger.
- Do NOT auto-export. Even after commit, ask before generating the Family XLSX.
- Do NOT silently register unknown categories - run with default `reject` mode first, show the Levenshtein suggestions, and ask before re-running with `register`. Typos look identical to legitimate new categories in the input - the user is the only one who can tell them apart.
- Do NOT reach for `pf-budget import` during a planning conversation. That subcommand is for bulk migration; the conversation path uses `plan add/update/remove` exclusively.
- Do NOT delete or move source data files. The query / report paths are read-only; only the budget / rules / categorize paths mutate the `pf_*` and `budget*` tables, and they own only those.
