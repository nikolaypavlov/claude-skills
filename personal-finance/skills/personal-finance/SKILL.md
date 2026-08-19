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
  - "перевіримо виконання бюджету", "budget status", "як я по плану"
  - "чи вистачає грошей", "do I have enough to cover the plan"
  Reads the shared store (MONOBANK_MCP_DATA_DIR, default
  ~/finances/data.db); needs monobank-mcp (for inline incremental
  sync before reports) and at least one ingest plugin installed.
allowed-tools: Bash, Read
---

# Personal finance: query, report, categorize, budget

## Pre-flight before any report, summary, or budget diff

1. Call the MCP tool `mcp__plugin_monobank-mcp_monobank__ensure_synced` with `max_wait_seconds=90` so Mono data is fresh. If the response includes `partial: true`, tell the user up-front ("Mono sync вийшов partial, можу продовжити з тим що є або зачекати - як зручніше?") and let them choose before continuing.
2. Privat24 has no API. Do NOT try to sync it - the user uploads XLSX exports manually via privat24-skill. Reports use whatever Privat data is already in the store; if `last_sync_ts.privat` in the report bundle looks stale, mention it but do not auto-import.
3. **Run the categorizer pass.** Not conditional - run it after every sync that precedes a reconciliation. Ingest plugins write to `<bank>_transactions` only; `tx_category` rows are populated by `pf-categorize`, and `pf-report` / `pf-budget diff` / `pf-query summarize` resolve category through `tx_category`. Skipping it is the step that silently breaks reconciliation: fresh rows stay uncategorized, fall out of `pf-budget diff`, and spend looks far lower than it is. The call is cheap (~1s for the typical month) and idempotent:

   ```bash
   pf-categorize --scope all              # before any budget reconciliation
   pf-categorize --scope last-n-days --n 30   # narrow query over a recent window
   ```

   Use `--scope all` whenever the answer is a budget diff or a month-end figure. `last-n-days` is for a one-off lookup where an older mis-categorized row cannot change the answer.

4. **Gate on a clean store before reporting any budget number.**

   ```bash
   pf-query summarize-uncategorized
   ```

   If the count is not 0: show the user the buckets, propose categories, and **stop**. Do not report a status, a variance, or a coverage figure off partially-categorized data - the numbers will move once the rest is classified, and a report that has to be retracted is worse than a slower one. Resume from step 3 once rules are added.

The pre-flight does NOT apply to "find a transaction" lookups, "list my accounts", budget planning, or any `pf-budget plan` operation - those are local and we don't want to add 60-90s of latency for a one-line answer.

## Invocation form

Entry points are exposed as `[project.scripts]` in the plugin's `pyproject.toml`. Invoke them via `uv run --directory <plugin-root> pf-query ...` / `uv run --directory <plugin-root> pf-report ...` / etc. `<plugin-root>` is wherever the plugin was installed (typically under `~/.claude/plugins/cache/<marketplace>/personal-finance/<version>/`). uv handles the project's venv (`uv sync` on first call as needed).

Two things bite in a non-interactive shell, and both look like the plugin is broken when they are not:

- Resolve the plugin root by globbing to the newest installed version rather than hardcoding one, so a version bump does not silently point at an old copy.
- `uv` is frequently a shell alias or function, which does not resolve in a non-interactive tool call and fails with "No such file or directory". Call the binary by its absolute path when a bare `uv` fails.

The store is `data.db` under `MONOBANK_MCP_DATA_DIR` when that variable is set, and under `~/finances` otherwise - the same resolution the ingest plugins use, so all three agree on one file. If a command appears to run against an empty database, check that variable before anything else: a wrong or unset value writes a second, empty store rather than failing.

## Read commands

### List accounts across all banks

```bash
pf-query accounts
```

Returns `{ok, detected_banks, accounts: [{bank, account_id, label, currency_code, ...}]}`. If no ingest plugin has populated tables, you'll see `warning: "no transaction sources detected..."` - tell the user which plugins to install.

### Current balances and real funds

```bash
pf-query balances
# optional cross-currency coverage view (opt-in, explicit rate):
pf-query balances --convert-to UAH --rate USD=44.5 [--rate EUR=48.0]
```

Returns `{ok, detected_banks, by_currency: {UAH: {accounts:[...], balance_minor_total, real_funds_minor_total, unknown_accounts}, ...}}`. Per account you get `balance_minor`, `credit_limit_minor`, `real_funds_minor` (= balance - credit line), `name`, `balance_synced_at`, and `balance_source`:

- `account` - authoritative balance stored on `<bank>_accounts` (monobank-mcp >= 0.3, refreshed by `monobank-mcp accounts` / backfill). Preferred; sidesteps the same-timestamp transfer-pair ambiguity.
- `transaction` - fallback to the newest transaction's running balance (privat, or a pre-0.3 mono row).
- `none` - no balance resolvable (dormant account, no synced tx); listed but excluded from totals and counted in `unknown_accounts`.

A credit line is baked into `balance_minor`, so `real_funds_minor` is the user's own money; a balance below the credit limit means debt. Totals are summed **within** each currency only. `--convert-to` is the single opt-in exception that crosses currencies - it needs an explicit `--rate` per held currency (use the user's own recent FOP transfer-pair rate, not a market quote); any currency without a rate is flagged in `converted.unconverted`, never silently dropped.

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
   - If the period already has an **active** budget, the draft copies that budget in full - every `kind`, including `one_time` - and the response carries `in_place: true`. This is the edit-the-current-month path: `plan commit` replaces the active budget, so a full copy is what keeps untouched lines alive.
   - Otherwise it is a new month: the draft copies only `kind=baseline` from the most recent prior active month, and `in_place` is `false`. `one_time` lines belong to the month they were planned for and are deliberately left behind.
   - `copied_from` in the response says which period was used. Pass `--copy-from` to override (e.g. `--copy-from 2026-06` to re-derive the current month from June, or `--copy-from ''` to start blank).

2. **Gather suggestions.** Call `pf-budget plan suggest --period YYYY-MM`. This returns history signals - seasonal gaps, monotonic trends, quarterly cadences, one-off deviations, excluded one_time items. Phrase them back as a small batch. Example:
   > Стартую з baseline попереднього місяця. Помітив 3 речі:
   > 1. Освіта/Курси (4 000) - минулого місяця був останній платіж. Далі зазвичай 0?
   > 2. Транспорт/Паливо було пів місяця через відпустку - повертаємо до 3 000?
   > 3. Подорожі/Готелі (10 000) - one-time відпустки, виключаю з шаблону.

3. **Walk through the dialogue.** When the user replies with a number (e.g. "Їжа/Продукти 12000"), translate to `pf-budget plan update`. When they confirm a batch, apply all those changes. When they introduce a new category, call `pf-budget plan add`. When they say "стоп, поверни X" or "передумав", call `pf-budget plan undo`. When they say "забудь все" or "почнемо спочатку", call `pf-budget plan cancel`.

4. **Multi-currency in one session.** The user can say "додай $300 на ремонт авто" and you call `pf-budget plan add --currency USD ...` on the same period's draft. The CLI creates the USD draft budget on demand. The user thinks of it as one plan.

5. **Confirm and commit.** When the user signals they're done ("Зафіксувати", "Готово"), summarise what's planned, then call `pf-budget plan commit --period YYYY-MM`. The draft replaces any existing active for the same period atomically.

6. **Optional Family export.** Ask "Експортувати для сімʼї?" Run `pf-budget export --period YYYY-MM --view family --out <path>.xlsx`. Family view has two tabs: `Огляд` (pretty grouped, with SUM formulas so spouse-side edits live-recompute) and `Деталі` (full flat list). Do NOT auto-export - only on the user's go-ahead.

### Conversation idioms

| User says | Subcommand |
|---|---|
| "плануємо липень" | `plan start --period 2026-07` |
| "так до всього" | apply every batched suggestion |
| "Їжа/Продукти 12000" | `plan update` (composite key) |
| "додай $300 на ремонт авто" | `plan add --currency USD --kind one_time` |
| "стоп, поверни курси" | `plan undo` |
| "забудь все" | `plan cancel` |
| "Зафіксувати" / "Готово" | `plan commit` |
| "експорт для сімʼї" / "для дружини" | `export --view family` |

### Planning subcommand reference

```bash
pf-budget plan start    --period 2026-07 [--copy-from 2026-06]   # default: own active budget if any, else prior month
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

**Filter the returned blocks by `status`.** While a draft exists for a period, `show` returns the active block AND the draft block side by side, and drafts and actives are designed to coexist during planning. Anything that reads `blocks` without filtering counts every draft line a second time: totals inflate, and a consumer that compares "how many lines are there now" against "how many were there before" flips to a false conclusion. Pick `status == "active"` for reporting actuals, `status == "draft"` for reviewing a plan in progress.

### Compare budget vs actuals

```bash
pf-budget diff --period 2026-06 [--currency UAH]
```

Joins budget lines with actuals via the same category-resolution path as `pf-query`. Categories that exist only in actuals (no budget line) surface as `in_budget=false`. Excludes `Перекази/СвоїКартки` by default to match the "real spending" convention.

Per-block `totals` keeps spend and income **separate** - report these three, not the raw net:

- `real_spend_minor` - sum of actual on non-income rows (spend; refunds net in).
- `income_minor` - sum of actual on `Дохід/*` rows.
- `remaining_minor` - planned outflow left (`spend_target - real_spend`; signed like targets: negative = budget still to spend, positive = overspent).

`actual_minor` is retained for back-compat but is a net-of-income figure: income lands on `Дохід/*` rows as positive amounts and silently shrinks it. Never present it as "spent" on its own.

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

## Budget status report (mid-month and month-end)

The question this report exists to answer is "is there enough money to cover what is planned". Everything else is supporting detail, so lead with the answer rather than building up to it.

Run the pre-flight in full (sync, categorize, gate on zero uncategorized), then `pf-budget diff --period <P> --currency <C>` once per currency that has an active budget.

### Deriving the figures

`totals` gives three figures directly and one by arithmetic:

| Figure | Where it comes from |
|---|---|
| Spent so far | `real_spend_minor` |
| Income received | `income_minor` |
| Planned spend for the month | `real_spend_minor + remaining_minor` |
| Obligations still ahead | planned spend minus spent so far |

There is no `spend_target` field in `totals`, and `target_minor` is not a substitute - it mixes in planned `Дохід/*` rows. Derive planned spend as above.

`remaining_minor` is signed like the targets: negative means budget still to spend, positive means overspent. State the direction in words; never hand the raw signed number to the user.

Planned income exists only when the user has planned `Дохід/*` lines, and equals `target_minor - (real_spend_minor + remaining_minor)`. When the budget has no income lines, report expected income as unknown. Substituting zero understates coverage and turns a healthy month into a false alarm.

### Converting to one currency

Coverage is the single place where currencies are combined. Every other section stays in its native currency. Fetch the rate at report time from the National Bank of Ukraine - public endpoint, no key, and no data about the user leaves the machine:

```bash
curl -sS -m 20 "https://bank.gov.ua/NBUStatService/v1/statdirectory/exchange?json"
```

Records look like `{"r030": 840, "cc": "USD", "rate": <float>, "exchangedate": "DD.MM.YYYY"}`. Match on `r030` - it is the ISO 4217 numeric code the store already uses - rather than on the `cc` string. Quote the rate and its `exchangedate` in the report header so the arithmetic stays checkable afterwards. Do not persist the rate anywhere.

Balances convert through the CLI, which already reports what it could not convert:

```bash
pf-query balances --convert-to UAH --rate USD=<rate>
```

Budget figures have no conversion flag - convert them in the report layer using that same rate, so both halves of the coverage line rest on one number. A currency with no rate is named in the text as unconverted and left out of the total, never silently dropped.

### Structure

Header: period, elapsed days as `<N> of <M> (<P>%)`, confirmation that the store is clean, and the NBU rate with its date.

**1. Coverage - the answer.** Two lines, both in the converted currency:

```
structural:   income for the month        vs   planned spend
              can the month's earnings fund the plan at all

operational:  funds on hand                vs   obligations still ahead
              + income still expected
              is there enough to reach the end of the month
```

Verdict on the margin over planned spend: at or above 10% is enough; 0 to 10% is tight, and name what is still ahead that makes it tight; below zero is not enough, and name what would have to give.

Then one sentence of prose. When the two lines disagree - the plan balances but liquidity is short, or the reverse - say which one is binding and why. That gap is usually a timing problem rather than a budget problem, and saying so prevents a needless cut to the plan.

**2. Per currency, in its native currency.** Three separate lines, never a single net figure: real spend against plan with the elapsed-day share alongside, income with its breakdown, and remaining planned budget stated in words as headroom or overspend.

**3. Overspent lines.** Table: category, plan, actual, percent, amount over.

**4. Running hot.** Lines at or above 75% with time still left in the month.

**5. Variable categories against pace.** Same table shape, with the elapsed-day share as the benchmark column.

**6. Fixed items,** split into those that have already fired and those that have not, with the total still ahead. This split is what makes a low spend percentage readable.

**7. Unplanned spend.** The `in_budget=false` rows, named.

**8. Forecast.** Variable run rate per day times days remaining, plus the fixed tail, against the plan.

**9. Verdict.** Two or three sentences: is the plan holding, and what to watch.

### Judging pace

Benchmark against the elapsed share of the month, but only where pace means anything:

- Daily and recurring categories (groceries, fuel, transport) are judged on pace. At 60% of the month, 60% of the line is on track.
- Lumpy fixed items (rent, tuition, insurance, annual payments) are judged on whether they have fired yet, not on pace. A rent line at 0% mid-month is normal before its due date and worth flagging after it.

Never present a headline "X% of plan spent at Y% of month" without this split. A month whose large fixed items are still ahead reads as a huge underspend and invites exactly the wrong conclusion.

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

### Fixing a category mid-reconciliation

The user reads a status report and corrects a line ("that one belongs in X"). Which command depends on whether the correction should outlive this transaction, and that is a question only the user can answer - ask when it is not stated. A recurring merchant is a rule; a person-to-person transfer or a cash withdrawal almost never is, because the same counterparty means something different next time.

```bash
# find the row the user is describing
pf-query find --query "<merchant or amount>" --limit 60

# permanent: this merchant is always this category
pf-rules add --match-field description --pattern '^<merchant>$' \
             --category "<Group/Name>" --priority 20 --apply

# one-off: only this transaction, leave the rules alone
pf-rules set-category --tx-id <tx-id> --category "<Group/Name>"
```

Anchor rule patterns (`^...$`) unless the user wants a prefix match - an unanchored fragment quietly captures unrelated merchants, and the damage only surfaces in a later month's report.

**Re-run `pf-budget diff` after any correction, before restating totals.** Every number already on screen is stale the moment a category moves, and quoting the pre-correction figure alongside the post-correction one is how a reconciliation stops adding up.

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
- Do NOT mix currencies into a single total in narrative. Report per-currency. The one exception is the coverage block of a budget status report, which is explicitly labelled as a converted view, carries the rate and its date, and names any currency it could not convert.
- Do NOT report a budget figure while `summarize-uncategorized` is non-zero. Show the buckets and stop instead.
- Do NOT substitute zero for planned income the user never planned. Unknown is a reportable answer; zero is a wrong one that reads as a shortfall.
- Do NOT auto-commit a budget draft. The user's explicit "Зафіксувати" / "Готово" is the only trigger.
- Do NOT auto-export. Even after commit, ask before generating the Family XLSX.
- Do NOT silently register unknown categories - run with default `reject` mode first, show the Levenshtein suggestions, and ask before re-running with `register`. Typos look identical to legitimate new categories in the input - the user is the only one who can tell them apart.
- Do NOT reach for `pf-budget import` during a planning conversation. That subcommand is for bulk migration; the conversation path uses `plan add/update/remove` exclusively.
- Do NOT delete or move source data files. The query / report paths are read-only; only the budget / rules / categorize paths mutate the `pf_*` and `budget*` tables, and they own only those.
