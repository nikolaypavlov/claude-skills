"""Query helpers backed by the dynamic UNION ALL view.

Kept separate from ``store.py`` (which owns pf_* schema bring-up) so
the schema-management and read-path logic stay independently
testable. The MCP tool layer (``tools.py``) is a thin wrapper over
these functions plus argument parsing.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Sequence
from typing import Any

from .types import Account, SummaryBucket, Transaction
from .view import (
    build_accounts_union_sql,
    build_tx_union_sql,
    discover_sources,
)

# Valid `group_by` values for ``summarize_spending`` mapped to the SQL
# expression evaluated against the joined UNION view. Hoisted to module
# scope so the supported keys are visible without diving into the
# function body, and so a typo lands as a clean ValueError with the
# canonical list in the message.
_GROUP_BY_EXPRESSIONS: dict[str, str] = {
    "category": "COALESCE(category_overrides.category, tx_category.category)",
    "mcc": "tx.mcc",
    "counterparty": "tx.counterparty",
    "currency": "tx.currency_code",
    "account": "tx.account_id",
    "bank": "tx.bank",
}


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

    ``category`` filter applies AFTER resolution (the WHERE predicate
    repeats the COALESCE expression because SQLite cannot reference a
    SELECT-list alias in WHERE), so passing ``category="Food"`` returns
    rows whose effective category is "Food" even when only a manual
    override set it.
    """
    sources = discover_sources(conn)
    union = build_tx_union_sql(sources)
    if union is None:
        return []
    where, params = _collect_filters(
        [
            ("tx.ts >= ?", from_ts, int),
            ("tx.ts < ?", to_ts, int),
            ("tx.account_id = ?", account_id, None),
            ("tx.bank = ?", bank, None),
            ("tx.currency_code = ?", currency_code, int),
            (
                "COALESCE(category_overrides.category, tx_category.category) = ?",
                category,
                None,
            ),
        ]
    )
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

    Valid ``group_by`` values live in ``_GROUP_BY_EXPRESSIONS``. Unknown
    values raise ``ValueError`` so callers fail loudly rather than
    silently grouping by something unexpected.
    """
    key_expr = _group_by_expression(group_by)
    sources = discover_sources(conn)
    union = build_tx_union_sql(sources)
    if union is None:
        return []
    where, params = _collect_filters(
        [
            ("tx.ts >= ?", from_ts, int),
            ("tx.ts < ?", to_ts, int),
            ("tx.account_id = ?", account_id, None),
            ("tx.bank = ?", bank, None),
            ("tx.currency_code = ?", currency_code, int),
        ]
    )
    sql = (
        f"SELECT {key_expr} AS key, tx.currency_code, "
        f"SUM(tx.amount_minor) AS total_minor, "
        f"COUNT(*) AS tx_count "
        f"FROM (\n{union}\n) AS tx "
        f"LEFT JOIN tx_category ON tx_category.tx_id = tx.id "
        f"LEFT JOIN category_overrides ON category_overrides.tx_id = tx.id "
        # Repeating the expression (rather than `GROUP BY key`) keeps us
        # compatible with SQLite < 3.38, which does not allow grouping
        # by SELECT-list alias.
        f"WHERE {' AND '.join(where)} "
        f"GROUP BY {key_expr}, tx.currency_code "
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


def _collect_filters(
    spec: list[tuple[str, Any, Any]],
) -> tuple[list[str], list[Any]]:
    """Build a WHERE-clause fragment list + bound-parameter list from a
    declarative spec of ``(clause, value, cast_or_None)`` tuples.
    Values that are ``None`` are skipped entirely - that's how a
    caller signals "no filter on this dimension".
    """
    where: list[str] = []
    params: list[Any] = []
    for clause, value, cast in spec:
        if value is None:
            continue
        where.append(clause)
        params.append(cast(value) if cast is not None else value)
    return where, params


def _group_by_expression(group_by: str) -> str:
    """Map the friendly ``group_by`` name to a SQL expression over the
    union view. Unknown values raise; we never silently fall back."""
    if group_by not in _GROUP_BY_EXPRESSIONS:
        raise ValueError(
            f"unsupported group_by={group_by!r}; "
            f"valid values: {sorted(_GROUP_BY_EXPRESSIONS.keys())}"
        )
    return _GROUP_BY_EXPRESSIONS[group_by]


def _row_to_tx(row: Sequence[Any]) -> Transaction:
    """Project a 14-column sqlite3 row to ``Transaction``. The Sequence
    type signals "must be indexable by position" - the previous
    Iterable annotation accepted single-pass generators that would
    consume on first index access."""
    return Transaction(
        id=row[0],
        bank=row[1],
        account_id=row[2],
        ts=int(row[3]),
        amount_minor=int(row[4]),
        currency_code=int(row[5]),
        op_amount_minor=int(row[6]) if row[6] is not None else None,
        op_currency_code=int(row[7]) if row[7] is not None else None,
        mcc=int(row[8]) if row[8] is not None else None,
        description=row[9],
        counterparty=row[10],
        balance_minor=int(row[11]) if row[11] is not None else None,
        imported_at=int(row[12]),
        category=row[13],
    )
