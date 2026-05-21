"""Query helpers backed by the dynamic UNION ALL view.

Kept separate from ``store.py`` (which owns pf_* schema bring-up) so
the schema-management and read-path logic stay independently
testable. The MCP tool layer (``tools.py``) is a thin wrapper over
these functions plus argument parsing.
"""

from __future__ import annotations

import sqlite3
from typing import Iterable

from .types import Account, SummaryBucket, Transaction
from .view import (
    build_accounts_union_sql,
    build_tx_union_sql,
    discover_sources,
)


def list_accounts(conn: sqlite3.Connection) -> list[Account]:
    """Return every account row from every discovered bank."""
    sources = discover_sources(conn)
    union = build_accounts_union_sql(sources)
    if union is None:
        return []
    rows = conn.execute(f"SELECT * FROM (\n{union}\n) ORDER BY bank, account_id")
    return [
        Account(
            account_id=r[0],
            bank=r[1],
            iban=r[2],
            type=r[3],
            currency_code=int(r[4]),
            masked_pan=r[5],
            label=r[6],
            opened_at=int(r[7]) if r[7] is not None else None,
        )
        for r in rows
    ]


def get_transactions(
    conn: sqlite3.Connection,
    *,
    from_ts: int | None = None,
    to_ts: int | None = None,
    account_id: str | None = None,
    bank: str | None = None,
    category: str | None = None,
    currency_code: int | None = None,
    limit: int = 500,
    offset: int = 0,
) -> list[Transaction]:
    """Return transactions matching the filters, with the resolved
    category stitched in (override > rule-assigned > NULL).

    ``category`` filter applies AFTER resolution, so passing
    ``category="Food"`` returns rows whose effective category is "Food"
    even when only a manual override set it.
    """
    sources = discover_sources(conn)
    union = build_tx_union_sql(sources)
    if union is None:
        return []
    where: list[str] = []
    params: list[object] = []
    if from_ts is not None:
        where.append("tx.ts >= ?")
        params.append(int(from_ts))
    if to_ts is not None:
        where.append("tx.ts < ?")
        params.append(int(to_ts))
    if account_id is not None:
        where.append("tx.account_id = ?")
        params.append(account_id)
    if bank is not None:
        where.append("tx.bank = ?")
        params.append(bank)
    if currency_code is not None:
        where.append("tx.currency_code = ?")
        params.append(int(currency_code))
    if category is not None:
        where.append(
            "COALESCE(category_overrides.category, tx_category.category) = ?"
        )
        params.append(category)
    where_sql = ("\nWHERE " + " AND ".join(where)) if where else ""
    params.extend([int(limit), int(offset)])
    sql = (
        f"SELECT tx.id, tx.bank, tx.account_id, tx.ts, tx.amount_minor, "
        f"tx.currency_code, tx.op_amount_minor, tx.op_currency_code, "
        f"tx.mcc, tx.description, tx.counterparty, tx.balance_minor, "
        f"tx.imported_at, "
        f"COALESCE(category_overrides.category, tx_category.category) AS category "
        f"FROM (\n{union}\n) AS tx "
        f"LEFT JOIN tx_category ON tx_category.tx_id = tx.id "
        f"LEFT JOIN category_overrides ON category_overrides.tx_id = tx.id"
        f"{where_sql} "
        f"ORDER BY tx.ts DESC, tx.id "
        f"LIMIT ? OFFSET ?"
    )
    rows = conn.execute(sql, params)
    return [_row_to_tx(r) for r in rows]


def summarize_spending(
    conn: sqlite3.Connection,
    *,
    from_ts: int,
    to_ts: int,
    group_by: str = "category",
    account_id: str | None = None,
    bank: str | None = None,
    currency_code: int | None = None,
) -> list[SummaryBucket]:
    """Group transactions by ``group_by`` and sum signed minor units
    per currency. Returns one row per (key, currency_code) pair.

    Valid ``group_by`` values: ``category``, ``mcc``, ``counterparty``,
    ``currency``, ``account``, ``bank``. Unknown values raise
    ``ValueError`` so callers fail loudly rather than silently
    grouping by something unexpected.
    """
    key_expr = _group_by_expression(group_by)
    sources = discover_sources(conn)
    union = build_tx_union_sql(sources)
    if union is None:
        return []
    where = ["tx.ts >= ?", "tx.ts < ?"]
    params: list[object] = [int(from_ts), int(to_ts)]
    if account_id is not None:
        where.append("tx.account_id = ?")
        params.append(account_id)
    if bank is not None:
        where.append("tx.bank = ?")
        params.append(bank)
    if currency_code is not None:
        where.append("tx.currency_code = ?")
        params.append(int(currency_code))
    sql = (
        f"SELECT {key_expr} AS key, tx.currency_code, "
        f"SUM(tx.amount_minor) AS total_minor, "
        f"COUNT(*) AS tx_count "
        f"FROM (\n{union}\n) AS tx "
        f"LEFT JOIN tx_category ON tx_category.tx_id = tx.id "
        f"LEFT JOIN category_overrides ON category_overrides.tx_id = tx.id "
        f"WHERE {' AND '.join(where)} "
        f"GROUP BY key, tx.currency_code "
        f"ORDER BY total_minor"
    )
    rows = conn.execute(sql, params)
    return [
        SummaryBucket(
            key="(uncategorized)" if r[0] is None else str(r[0]),
            currency_code=int(r[1]),
            total_minor=int(r[2] or 0),
            tx_count=int(r[3]),
        )
        for r in rows
    ]


def _group_by_expression(group_by: str) -> str:
    """Map the friendly ``group_by`` name to a SQL expression over the
    union view. Unknown values raise; we never silently fall back."""
    mapping = {
        "category": "COALESCE(category_overrides.category, tx_category.category)",
        "mcc": "tx.mcc",
        "counterparty": "tx.counterparty",
        "currency": "tx.currency_code",
        "account": "tx.account_id",
        "bank": "tx.bank",
    }
    if group_by not in mapping:
        raise ValueError(
            f"unsupported group_by={group_by!r}; "
            f"valid values: {sorted(mapping.keys())}"
        )
    return mapping[group_by]


def _row_to_tx(row: Iterable) -> Transaction:
    r = tuple(row)
    return Transaction(
        id=r[0],
        bank=r[1],
        account_id=r[2],
        ts=int(r[3]),
        amount_minor=int(r[4]),
        currency_code=int(r[5]),
        op_amount_minor=int(r[6]) if r[6] is not None else None,
        op_currency_code=int(r[7]) if r[7] is not None else None,
        mcc=int(r[8]) if r[8] is not None else None,
        description=r[9],
        counterparty=r[10],
        balance_minor=int(r[11]) if r[11] is not None else None,
        imported_at=int(r[12]),
        category=r[13],
    )
