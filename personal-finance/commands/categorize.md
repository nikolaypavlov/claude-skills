---
description: Run categorization over the personal finance data and review uncategorized transactions
---

# /personal-finance:categorize

Run the categorizer pass over `~/finances/data.db`, then walk the user through any remaining uncategorized transactions and (with explicit confirmation) add rules or one-off overrides.

## Step 1: refresh Mono data, then categorize

Before reading anything from the store, call `mcp__monobank__ensure_synced` with `max_wait_seconds=90` so the categorizer doesn't miss recent transactions. If `partial: true` comes back, tell the user up front.

Then run the pass. Pick the scope based on what the user asked:

```bash
# Whole store (use after a backfill or when the user wants a full recategorize)
uv run --directory <plugin-root> pf-categorize --scope all

# Recent activity only (typical monthly review)
uv run --directory <plugin-root> pf-categorize --scope last-n-days --n 30
```

Output:

```json
{
  "ok": true,
  "categorized_count": 42,
  "no_match_count": 7,
  "overrides_applied": 1,
  "active_rules": 96,
  "scope": {"scope": "last-n-days", "from_ts": 1747...}
}
```

`categorized_count` are rows just written to `tx_category`. `no_match_count` are the ones the user needs to triage (next step). `overrides_applied` reflects entries imported from `~/finances/rules/overrides.local.yaml` into `category_overrides`.

## Step 2: surface the remaining uncategorized

Fetch them so you can show concrete merchant names to the user:

```bash
uv run --directory <plugin-root> pf-query list \
  --from <month-start-ts> --to <month-end-ts> --category "" --limit 200
```

(Alternative: pull the report bundle and read `uncategorized_transactions[]` from there.)

Group by counterparty / description and present a short summary - "X transactions at Glovo, Y at uklon, Z at АТБ" - so the user can answer in batches instead of one-by-one.

## Step 3: propose a rule, preview, apply

For each cluster the user agrees to categorize, propose a `pf-rules add` call and **preview first**:

```bash
# Preview only (no --apply): rule is inserted but NOT retroactively backfilled
uv run --directory <plugin-root> pf-rules add \
  --match-field counterparty \
  --pattern "GLOVO|GLOVO UA" \
  --category "Їжа/Доставка"
```

Output includes `would_affect_count` and a sample of 5 transactions. Show that to the user. On yes:

```bash
# Backfill the rule retroactively
uv run --directory <plugin-root> pf-rules apply --rule-id <id>
```

If the user wants to skip the two-step preview-then-apply (e.g. they typed a known-good regex), you can pass `--apply` to `pf-rules add` so the insert + backfill happen in one call. Default behaviour is preview because regex typos are silent and easy to make.

## Step 4: one-off pins (set-override)

When a single transaction is genuinely an exception ("this charge looks like McDonald's but it was a birthday card from my mom"), do NOT add a rule. Use `set-override`:

```bash
uv run --directory <plugin-root> pf-rules set-override \
  --tx-id mono_abc123 \
  --category "Подарунки" \
  --note "Birthday card, miscoded by merchant"
```

Overrides win over both rule-assigned categories and `tx_category` rows at query time, so the user sees the pin reflected in every future report without polluting the rule set.

## Step 5: enumerate the rule set (optional)

When the user asks "what rules do I have?" or wants to see what categories the seed covers:

```bash
uv run --directory <plugin-root> pf-rules list [--enabled-only] [--source seed-mcc]
```

Sources are: `seed-mcc` (bundled MCC -> category map), `seed-description` (bundled brand regexes), `local-counterparty` (user's `~/finances/rules/counterparty.local.yaml`), `db` (rules the user added via `pf-rules add`).

## What NOT to do

- Do NOT call `pf-rules apply` without first showing the preview from `add` (unless the user explicitly said "skip the preview").
- Do NOT add a rule for a single transaction - use `set-override` instead. Rule list pollution is its own form of debt.
- Do NOT auto-categorize and apply without the user yes-ing each proposed rule. The friction is the feature.
- Do NOT write raw SQL against `~/finances/data.db`. Always go through the `pf-*` scripts.
