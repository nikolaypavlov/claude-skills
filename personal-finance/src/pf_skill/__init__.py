"""personal-finance umbrella skill: CLI entry points for query, report,
categorization, and rule management over the shared ~/finances/data.db.

The package owns ``pf_*`` tables (categorization rules, manual overrides)
and reads ``<bank>_transactions`` tables installed by ingest plugins
(monobank-mcp, privat24-skill) via runtime UNION ALL discovery in
``pf_skill.common.view``.

Activation is via the Claude Code Skill at ``skills/personal-finance/``;
the user never invokes these scripts directly. See ``SKILL.md`` for the
trigger phrases and invocation cookbook.
"""
