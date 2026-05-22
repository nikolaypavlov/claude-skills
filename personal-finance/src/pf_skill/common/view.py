"""Runtime discovery of ``<bank>_transactions`` / ``<bank>_accounts``
tables and dynamic UNION ALL SQL construction.

The umbrella plugin owns no transaction storage of its own. It reads
whatever ingest plugins have installed at the moment - today that's
``monobank-mcp`` (mono_*) and ``privat24-skill`` (privat_*); tomorrow a
hypothetical ``revolut-mcp`` would land as ``revolut_*`` without any
code change here.

We treat each detected bank's table as a "view source" and build a
UNION ALL projection over all sources at query time. Every detected
bank table is required to expose the columns in ``COMMON_TX_COLUMNS`` /
``COMMON_ACCOUNT_COLUMNS`` per the cross-plugin contract in
``docs/transactions-schema.md``. If a future bank omits a column the
projected query will fail at execute time with
``OperationalError: no such column`` - we do NOT silently inject
``NULL`` for absent columns, because that would mask a real contract
violation.
"""

from __future__ import annotations

import re
import sqlite3
from dataclasses import dataclass

# Columns we expose at the umbrella query layer. Order matters - all
# UNION ALL legs must select these in the same sequence. The literal
# ``bank`` column is materialised from the bank prefix in the projection,
# so it is selected from the discovered prefix rather than from a real
# column in the source table.
COMMON_TX_COLUMNS: tuple[str, ...] = (
    "id",
    "bank",
    "account_id",
    "ts",
    "amount_minor",
    "currency_code",
    "op_amount_minor",
    "op_currency_code",
    "mcc",
    "description",
    "counterparty",
    "balance_minor",
    "imported_at",
)

COMMON_ACCOUNT_COLUMNS: tuple[str, ...] = (
    "account_id",
    "bank",
    "iban",
    "type",
    "currency_code",
    "masked_pan",
    "label",
    "opened_at",
)

# Per-bank tables we know how to read. New banks just add an entry. The
# regex deliberately rejects underscores in the prefix so a bank named
# "my_other" doesn't collide with our suffix convention.
_TX_TABLE_PATTERN = re.compile(r"^(?P<bank>[a-z][a-z0-9]*)_transactions$")
_ACCOUNT_TABLE_PATTERN = re.compile(r"^(?P<bank>[a-z][a-z0-9]*)_accounts$")


@dataclass(frozen=True)
class DiscoveredSources:
    """Tables detected in the shared store. Each tuple element is the
    bank prefix - e.g. ``"mono"`` or ``"privat"``."""

    tx_banks: tuple[str, ...]
    account_banks: tuple[str, ...]

    def has_any_tx(self) -> bool:
        return bool(self.tx_banks)


def discover_sources(conn: sqlite3.Connection) -> DiscoveredSources:
    """Inspect ``sqlite_master`` and return the bank prefixes whose
    ``<bank>_transactions`` / ``<bank>_accounts`` tables are present.

    Banks are reported sorted alphabetically so UNION ALL output and
    test expectations stay stable.
    """
    names = {
        row[0]
        for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
    }
    tx_banks = sorted(
        m.group("bank") for name in names if (m := _TX_TABLE_PATTERN.match(name))
    )
    account_banks = sorted(
        m.group("bank") for name in names if (m := _ACCOUNT_TABLE_PATTERN.match(name))
    )
    return DiscoveredSources(tuple(tx_banks), tuple(account_banks))


def build_tx_union_sql(sources: DiscoveredSources) -> str | None:
    """Build a parenthesised UNION ALL SELECT over every detected
    ``<bank>_transactions`` table, projecting to ``COMMON_TX_COLUMNS``.

    Returns ``None`` when no sources are present so the caller can
    short-circuit with a friendly "no data" outcome instead of executing
    invalid SQL.

    The returned string is a SELECT (no trailing semicolon) so it can be
    embedded in larger queries: ``SELECT * FROM (<union>) WHERE ...``.
    """
    if not sources.tx_banks:
        return None
    legs = [
        _leg_sql(bank, "transactions", COMMON_TX_COLUMNS) for bank in sources.tx_banks
    ]
    return "\n  UNION ALL\n".join(legs)


def build_accounts_union_sql(sources: DiscoveredSources) -> str | None:
    """UNION ALL SELECT over every detected ``<bank>_accounts`` table."""
    if not sources.account_banks:
        return None
    legs = [
        _leg_sql(bank, "accounts", COMMON_ACCOUNT_COLUMNS)
        for bank in sources.account_banks
    ]
    return "\n  UNION ALL\n".join(legs)


def _leg_sql(bank: str, table_suffix: str, columns: tuple[str, ...]) -> str:
    """One UNION ALL leg projecting a bank-specific table to the
    common shape. Column names are inlined; only the discovered ``bank``
    prefix is interpolated, and the regex guarantees it is
    ``[a-z][a-z0-9]*`` so no SQL escaping is needed for the string
    literal. The table identifier is double-quoted so a future bank
    prefix that happens to be a SQLite reserved word (``group``,
    ``order``, etc.) still produces valid SQL."""
    projected = ", ".join(
        f"'{bank}' AS bank" if col == "bank" else col for col in columns
    )
    return f'  SELECT {projected} FROM "{bank}_{table_suffix}"'
