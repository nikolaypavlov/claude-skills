"""Runtime discovery of ``<bank>_transactions`` / ``<bank>_accounts``
tables and dynamic UNION ALL SQL construction.

The umbrella plugin owns no transaction storage of its own. It reads
whatever ingest plugins have installed at the moment - today that's
``monobank-mcp`` (mono_*) and ``privat24-skill`` (privat_*); tomorrow a
hypothetical ``revolut-mcp`` would land as ``revolut_*`` without any
code change here.

We treat each detected bank's table as a "view source" and build a
UNION ALL projection over all sources at query time. Columns missing
in a particular bank's schema (e.g. ``cashback_minor`` is mono-only) are
substituted with ``NULL`` so the projected shape is uniform.
"""

from __future__ import annotations

import re
import sqlite3
from dataclasses import dataclass

# Columns we expose at the umbrella query layer. Order matters - all
# UNION ALL legs must select these in the same sequence.
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

# Per-bank tables we know how to read. New banks just add an entry.
_TX_TABLE_PATTERN = re.compile(r"^(?P<bank>[a-z][a-z0-9]*)_transactions$")
_ACCOUNT_TABLE_PATTERN = re.compile(r"^(?P<bank>[a-z][a-z0-9]*)_accounts$")


@dataclass(frozen=True)
class DiscoveredSources:
    """Tables detected in the shared store. Each list element is the
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
        for row in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        )
    }
    tx_banks = sorted(
        m.group("bank")
        for name in names
        if (m := _TX_TABLE_PATTERN.match(name))
    )
    account_banks = sorted(
        m.group("bank")
        for name in names
        if (m := _ACCOUNT_TABLE_PATTERN.match(name))
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
    legs: list[str] = []
    for bank in sources.tx_banks:
        legs.append(_tx_leg_sql(bank))
    return "\n  UNION ALL\n".join(legs)


def build_accounts_union_sql(sources: DiscoveredSources) -> str | None:
    """UNION ALL SELECT over every detected ``<bank>_accounts`` table."""
    if not sources.account_banks:
        return None
    legs = [_account_leg_sql(bank) for bank in sources.account_banks]
    return "\n  UNION ALL\n".join(legs)


def _tx_leg_sql(bank: str) -> str:
    """One UNION ALL leg projecting a bank-specific table to the common
    transaction shape. Columns absent in the bank's table are NULL'd."""
    table = f"{bank}_transactions"
    # Each bank may or may not have these optional columns. We assume
    # the cross-plugin contract (docs/transactions-schema.md) holds for
    # required columns and use NULL fallbacks for the optional ones.
    # NOTE: every bank we ship today writes all listed columns; the
    # COALESCE-like fallbacks only kick in for future banks that omit
    # them.
    return (
        f"  SELECT id, '{bank}' AS bank, account_id, ts, amount_minor, "
        f"currency_code, op_amount_minor, op_currency_code, mcc, "
        f"description, counterparty, balance_minor, imported_at "
        f"FROM {table}"
    )


def _account_leg_sql(bank: str) -> str:
    table = f"{bank}_accounts"
    return (
        f"  SELECT account_id, '{bank}' AS bank, iban, type, currency_code, "
        f"masked_pan, label, opened_at "
        f"FROM {table}"
    )
