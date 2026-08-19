---
description: Budget status - sync, categorize, then reconcile actuals against the plan and answer whether the money covers it
argument-hint: "[YYYY-MM] (default: current month)"
---

# /personal-finance:status

Reconcile actual spending against the active budget for period **$1** (empty means the current calendar month) and answer the question the report exists for: is there enough money to cover what is planned.

Do the steps in order. Step 3 is the one that silently breaks the reconciliation when skipped - freshly synced rows are uncategorized, fall out of `pf-budget diff`, and spend looks far lower than it is.

`<plugin-root>` below is this plugin's installed directory; see "Invocation form" in the skill for how to resolve it.

## Step 1: sync Mono

Call `mcp__plugin_monobank-mcp_monobank__ensure_synced` with `max_wait_seconds=90`.

- **`caught_up: true` is the only green light.** It means every account was walked to the end. `rows_added: 0` proves nothing on its own - an account with `status: unattempted` or `remaining_chunks > 0` was never fetched, and its window is unchecked.
- On `caught_up: false`, run the `monobank-mcp sync` CLI in the background (the API rate limit is one call per 60 seconds) and wait for it. Tell the user if it stays behind rather than reporting off unchecked data.
- On `suspected_missing_rows: true`, stop and say so: the named accounts are missing rows inside an already-synced window, which `sync` cannot recover. Only `monobank-mcp backfill --from <date> --account <id>` closes that. A budget status off those numbers is wrong by exactly the missing spend.
- Do not poll for the background sync on a timer or schedule a wake-up for it. The harness re-invokes you when the task exits; a self-firing check re-runs this whole command and loops.
- If the MCP server is missing or has no token, say so once and continue on the existing store. Stale data with a warning beats no answer.

Privat24 has no API. If its last sync looks stale, mention it and ask for a fresh XLSX export - never auto-import.

## Step 2: categorize

```bash
uv run --directory <plugin-root> pf-categorize --scope all
```

## Step 3: verify the store is clean

```bash
uv run --directory <plugin-root> pf-query summarize-uncategorized
```

If the count is not 0, show the buckets, propose categories, and **stop here**. Add rules with the user's confirmation, re-run step 2, and only then continue. A status reported off partially-categorized data has to be retracted once the rest is classified.

## Step 4: reconcile per currency

For each currency with an active budget:

```bash
uv run --directory <plugin-root> pf-budget diff --period <YYYY-MM> --currency <CODE>
```

Read `real_spend_minor`, `income_minor` and `remaining_minor` as three separate figures. `actual_minor` nets income into spend and must never be reported on its own. `remaining_minor` is signed like the targets - negative is headroom, positive is overspend - so say the direction in words.

## Step 5: get the rate and the balances

```bash
curl -sS -m 20 "https://bank.gov.ua/NBUStatService/v1/statdirectory/exchange?json"
uv run --directory <plugin-root> pf-query balances --convert-to UAH --rate USD=<rate>
```

Match the NBU record on `r030` (the ISO 4217 numeric code the store uses), and carry its `exchangedate` into the report header.

## Step 6: report

Compose the report exactly as "Budget status report" in the skill describes: coverage first (structural and operational, with the 10% margin verdict), then per-currency detail in native currency, overspent lines, hot lines, variables against pace, fixed items split by whether they have fired, unplanned spend, forecast, verdict.

Judge daily and recurring categories on pace against the elapsed share of the month; judge lumpy fixed items on whether they have fired yet. Never lead with a bare "X% of plan at Y% of month" - without that split it reads as a large underspend when the fixed tail is simply still ahead.

## Corrections

When the user reassigns a transaction while reading the report, ask whether it should be permanent (`pf-rules add --apply`) or one-off (`pf-rules set-category --tx-id`) when they have not said. Re-run step 4 before restating any total.
