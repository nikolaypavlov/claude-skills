---
description: "Categorize uncategorized transactions in ~/finances/data.db (PR#4 placeholder)."
allowed-tools: ["mcp__personal_finance__*"]
---

# /personal-finance:categorize (PR#4)

The categorizer + rule-management surface ships in PR#4. In 0.1.0 this
command is a placeholder so the skill's marketplace listing already
advertises the slash command.

When invoked today, tell the user:

> The categorization pipeline ships in the next release of
> personal-finance (PR#4 in `docs/personal-finance-design.md`). Today
> the umbrella exposes only the read-path tools - `data_sources`,
> `list_accounts`, `get_transactions`, `summarize_spending`. Once PR#4
> lands you'll be able to run rule-based + interactive categorization
> over the existing data without re-importing anything.

Do not attempt to write to `pf_*` tables yet - the write-path tools
(`set_category`, `add_rule`, `apply_rules_retroactively`,
`categorize_uncategorized`) raise `RuntimeError("This tool ships in
PR#4 ...")` in 0.1.0.
