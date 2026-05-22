---
description: Run categorization over the personal finance data and review uncategorized transactions
---

# /personal-finance:categorize

Run the categorization pass over `~/finances/data.db`, then walk the user through any remaining uncategorized transactions and (with explicit confirmation) add rules or one-off overrides.

## Status: stub until PR#4

The mutation CLIs (`pf-categorize`, `pf-rules add`, `pf-rules set-category`, etc.) land in PR#4. For PR#3 the umbrella skill is read-only.

What works today:
- Telling the user "no categorization run is wired up yet; install monobank-mcp + privat24-skill and import some data, then come back once PR#4 lands."
- Using `pf-query` and `pf-report` to surface uncategorized transactions in reports (see `skills/personal-finance/SKILL.md`).

## Once PR#4 ships, the flow will be

1. `uv run --directory <plugin-root> pf-categorize --scope all` (or `--scope last-n-days --n 30`).
2. Report `{categorized_count, remaining_count}` to the user.
3. For each remaining uncategorized transaction, propose a category (matching counterparty or MCC) and a candidate rule.
4. On user confirmation, run `pf-rules add --match-field <field> --pattern <regex> --category <c>` (preview only). Show `would_affect_count` + a sample of 5.
5. If the user approves the preview, run `pf-rules apply --rule-id <id>`.
6. If the user just wants a one-off pin, run `pf-rules set-category --tx-id <id> --category <c>`.

Never apply a rule retroactively without showing the preview first. Never auto-add rules without an explicit user yes.
