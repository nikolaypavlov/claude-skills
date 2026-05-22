---
description: Run categorization over the personal finance data and review uncategorized transactions
---

# /personal-finance:categorize

Run the categorizer pass over `~/finances/data.db`, then walk the user through any remaining uncategorized transactions and (with explicit confirmation) add rules or one-off overrides.

## Step 1: refresh Mono data, then categorize

Before reading anything from the store, call `mcp__monobank__ensure_synced` with `max_wait_seconds=90` so the categorizer doesn't miss recent transactions.

- If `partial: true` comes back, tell the user up front (some recent rows may still be missing).
- If the call errors entirely - typically `MCP error -32042: monobank-mcp has no API token loaded`, or the MCP server is not installed - tell the user once that `/monobank-mcp:setup` would refresh the data, then **proceed on the existing DB**. Do not block the categorize flow; older Mono rows and any Privat24 imports are still fair game.

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
# --from / --to accept ISO 8601 dates OR unix seconds. Prefer ISO - no math.
# --category "" means "show only uncategorized rows".
uv run --directory <plugin-root> pf-query list \
  --from 2026-01-01 --to 2027-01-01 --category "" --limit 200
```

Alternative: `pf-report --from <date> --to <date>` returns a JSON bundle whose top-level `uncategorized_transactions[]` is the same row shape. Useful when you also want period totals in one call.

Group by counterparty / description and present a short summary - "X transactions at Glovo, Y at uklon, Z at АТБ" - so the user can answer in batches instead of one-by-one.

A practical pattern: pipe the `transactions[]` array through `jq` (or read it yourself) and cluster by `description` + `mcc`. Example:

```bash
uv run --directory <plugin-root> pf-query list \
  --from 2026-01-01 --to 2027-01-01 --category "" --limit 200 \
  | jq -r '.transactions | group_by(.description) | map({merchant: .[0].description, mcc: .[0].mcc, count: length, sum_minor: (map(.amount_minor) | add)}) | sort_by(-.count)'
```

Note: `pf-query summarize --group-by counterparty` exists but does **not** accept `--category ""`, so it aggregates all transactions, not just uncategorized ones. For uncategorized clustering, use the `list` + group-in-memory approach above.

## Step 3: propose a rule, preview, apply

**Before naming any new category, enumerate the ones already in use** so suggestions match the user's existing taxonomy (don't invent `Транспорт/Паркінг` if `Авто/Паркінг` is already established):

```bash
uv run --directory <plugin-root> pf-query summarize \
  --from 2026-01-01 --to 2027-01-01 --group-by category
```

The `buckets[]` payload lists every distinct category currently assigned, with row counts. Reference that list when proposing new names to the user.

For each cluster the user agrees to categorize, propose a `pf-rules add` call and **preview first**.

`--match-field` accepts three values; each comes with a different pattern type and a default priority (lower priority wins on conflict):

| `--match-field` | pattern type   | default priority |
| --------------- | -------------- | ---------------: |
| `description`   | regex          |              100 |
| `counterparty`  | regex          |              200 |
| `mcc`           | exact integer  |              300 |

Override with `--priority` only when you intend to break the default ranking (e.g. forcing a counterparty rule to beat a description rule).

```bash
# Preview only (no --apply): rule is inserted but NOT retroactively backfilled
uv run --directory <plugin-root> pf-rules add \
  --match-field counterparty \
  --pattern "GLOVO|GLOVO UA" \
  --category "Їжа/Доставка"
```

Output includes `would_affect_count` and a sample of 5 transactions. Show that to the user. On yes:

> `would_affect_count` counts **uncategorized rows only** - exactly what a subsequent `apply` would write. If the pattern matches transactions that already have a category, those are not in the count. So a regex that obviously matches the user's data but reports `would_affect_count: 0` usually means the merchant is already categorized by an earlier rule, not that the regex is broken. To double-check, search by description: `pf-query find --query "<merchant>"`.

```bash
# Backfill the rule retroactively
uv run --directory <plugin-root> pf-rules apply --rule-id <id>
```

If the user wants to skip the two-step preview-then-apply (e.g. they typed a known-good regex), you can pass `--apply` to `pf-rules add` so the insert + backfill happen in one call. Default behaviour is preview because regex typos are silent and easy to make.

**MCC rules are NOT regex.** With `--match-field mcc` the `--pattern` is compared as an exact integer string - `"5211|5251"` matches nothing (and the underlying `Rule.matches` swallows `re.error`, so the failure is silent). For multiple MCCs, issue one `pf-rules add` per code.

## Step 4: one-off pins (set-override)

When a single transaction is genuinely an exception ("this charge looks like McDonald's but it was a birthday card from my mom"), do NOT add a rule. Use `set-override`:

```bash
uv run --directory <plugin-root> pf-rules set-override \
  --tx-id mono_abc123 \
  --category "Подарунки" \
  --note "Birthday card, miscoded by merchant"
```

Overrides win over both rule-assigned categories and `tx_category` rows at query time, so the user sees the pin reflected in every future report without polluting the rule set.

### `set-category` vs `set-override`

Both pin a single transaction. They differ in where the pin lives and what it survives.

| command         | writes to            | beats a future matching rule? | accepts `--note`? |
| --------------- | -------------------- | :---------------------------: | :---------------: |
| `set-category`  | `tx_category`        |  no - same table the categorizer writes; first writer wins | no |
| `set-override`  | `category_overrides` |  **yes** - read-path picks override over rule + `tx_category` | yes |

**Default to `set-override`** for one-off pins. It documents the exception (`--note`) and stays correct even if you later add a rule that would have matched. Use `set-category` only when you want the manual mark to act exactly like a rule-assigned category - e.g. you are categorizing a tx that no rule covers AND no future rule should cover.

## Step 5: enumerate the rule set (optional)

When the user asks "what rules do I have?" or wants to see what categories the seed covers:

```bash
uv run --directory <plugin-root> pf-rules list [--enabled-only] [--source seed-mcc]
```

Sources are: `seed-mcc` (bundled MCC -> category map), `seed-description` (bundled brand regexes), `local-counterparty` (user's `~/finances/rules/counterparty.local.yaml`), `db` (rules the user added via `pf-rules add`).

Output (truncated to one rule):

```json
{
  "ok": true,
  "count": 113,
  "rules": [
    {
      "rule_id": 7,
      "priority": 100,
      "match_field": "description",
      "pattern": "MAISW CAR WASH",
      "category": "Авто/Мийка",
      "source": "db",
      "enabled": true
    }
  ]
}
```

`rule_id` is the integer used by `pf-rules apply --rule-id <id>`. It is non-null only for `db` rules; seed-* and `local-counterparty` rules expose `rule_id: null` because they are read-only and cannot be re-applied through this CLI (regenerated automatically each pass).

## What NOT to do

- Do NOT call `pf-rules apply` without first showing the preview from `add` (unless the user explicitly said "skip the preview").
- Do NOT add a rule for a single transaction - use `set-override` instead. Rule list pollution is its own form of debt.
- Do NOT auto-categorize and apply without the user yes-ing each proposed rule. The friction is the feature.
- Do NOT write raw SQL against `~/finances/data.db`. Always go through the `pf-*` scripts.
