"""Personal finance MCP umbrella server.

Reads `<bank>_transactions` tables produced by ingest plugins
(monobank-mcp, privat24-skill) via runtime sqlite_master discovery.
Owns `pf_*` tables - categorization rules, manual overrides, version
tracker. Does NOT touch tables owned by other plugins.

See ``docs/personal-finance-design.md`` (v2.1) for the architecture and
``docs/transactions-schema.md`` (v1.0) for the cross-plugin row shape.
"""

__version__ = "0.1.0"
