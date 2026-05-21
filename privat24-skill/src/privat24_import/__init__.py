"""Privat24 statement (XLSX) import skill.

Owns the ``privat_*`` tables in ``~/finances/data.db``. Reads only its own
schema; does not touch tables owned by other plugins. See
``docs/transactions-schema.md`` for the cross-plugin shape contract.
"""

__version__ = "0.1.0"
