"""Shared modules used by every ``pf-*`` CLI entry point.

- ``store``: SQLite open + pf_* migration applier.
- ``view``: runtime UNION ALL discovery over ``<bank>_transactions`` /
  ``<bank>_accounts`` tables.
- ``types``: TypedDict shapes for the projected common view.
- ``queries``: read helpers (list_accounts, get_transactions,
  summarize_spending, find_transactions).
- ``currencies``: ISO 4217 numeric <-> alpha code helpers.

The CLI entry points (``pf_skill.query``, ``pf_skill.report``, and the
PR#4 ``pf_skill.categorize`` / ``pf_skill.rules_cli``) are thin argparse
wrappers around these modules.
"""
