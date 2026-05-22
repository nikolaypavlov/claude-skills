"""Query helpers backed by the dynamic UNION ALL view.

Kept separate from ``store.py`` (which owns pf_* schema bring-up) so
the schema-management and read-path logic stay independently
testable. The CLI entry points (``pf_skill.query``, ``pf_skill.report``)
are thin wrappers over these functions plus argument parsing and JSON
serialisation.

The SQL fragments at the top of this module (``TX_COLUMNS_SQL``,
``CATEGORY_EXPR``, ``CATEGORY_JOIN_SQL``) are the canonical source for
the cross-bank read shape; ``reports.py`` reuses them so a column
added (or category-resolution rule changed) here propagates to both
single-query and bundle paths.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Sequence
from typing import Any

from .types import Account, SummaryBucket, Transaction
from .view import (
    DiscoveredSources,
    build_accounts_union_sql,
    build_tx_union_sql,
    discover_sources,
)

# Canonical SELECT-list for transactions projected through the UNION
# view. Used directly by ``get_transactions``, ``find_transactions``,
# and the ``reports.py`` helpers - any column added here needs to also
# appear in ``view.COMMON_TX_COLUMNS`` (and vice-versa).
TX_COLUMNS_SQL = (
    "tx.id, tx.bank, tx.account_id, tx.ts, tx.amount_minor, "
    "tx.currency_code, tx.op_amount_minor, tx.op_currency_code, "
    "tx.mcc, tx.description, tx.counterparty, tx.balance_minor, "
    "tx.imported_at"
)

# Resolved-category expression: override beats rule-assigned beats NULL.
# Repeated rather than aliased because SQLite < 3.38 cannot reference
# a SELECT-list alias from WHERE / GROUP BY clauses.
CATEGORY_EXPR = "COALESCE(category_overrides.category, tx_category.category)"

# Join boilerplate for stitching the resolved category onto a row from
# the UNION view.
CATEGORY_JOIN_SQL = (
    "LEFT JOIN tx_category ON tx_category.tx_id = tx.id "
    "LEFT JOIN category_overrides ON category_overrides.tx_id = tx.id"
)

# Valid ``group_by`` values for ``summarize_spending`` mapped to the
# SQL expression evaluated against the joined UNION view. Hoisted to
# module scope so the supported keys are visible without diving into
# the function body, and so a typo lands as a clean ValueError with
# the canonical list in the message.
_GROUP_BY_EXPRESSIONS: dict[str, str] = {
    "category": CATEGORY_EXPR,
    "mcc": "tx.mcc",
    "counterparty": "tx.counterparty",
    "currency": "tx.currency_code",
    "account": "tx.account_id",
    "bank": "tx.bank",
}

# Group-by keys allowed for ``summarize_uncategorized``. Subset of
# ``_GROUP_BY_EXPRESSIONS`` - ``category`` is excluded because the
# function already filters to "category IS NULL" rows, so grouping by
# category would always produce a single bucket.
_UNCATEGORIZED_GROUP_BY_EXPRESSIONS: dict[str, str] = {
    "description": "tx.description",
    "counterparty": "tx.counterparty",
    "mcc": "tx.mcc",
}


def valid_group_by_keys() -> tuple[str, ...]:
    """Tuple of supported ``--group-by`` values, in stable order for
    user-facing error messages and argparse ``choices=``."""
    return tuple(_GROUP_BY_EXPRESSIONS.keys())


def valid_uncategorized_group_by_keys() -> tuple[str, ...]:
    """Tuple of supported ``--group-by`` values for
    ``summarize_uncategorized``."""
    return tuple(_UNCATEGORIZED_GROUP_BY_EXPRESSIONS.keys())


def list_accounts(
    conn: sqlite3.Connection,
    *,
    sources: DiscoveredSources | None = None,
) -> list[Account]:
    """Return every account row from every discovered bank.

    ``sources`` is optional; pass it when the caller has already
    discovered to avoid a second ``sqlite_master`` round-trip (e.g.
    ``cmd_accounts`` reads ``detected_banks`` from the same probe).
    """
    if sources is None:
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
    repeats ``CATEGORY_EXPR`` because SQLite cannot reference a
    SELECT-list alias in WHERE), so passing ``category="Food"`` returns
    rows whose effective category is "Food" even when only a manual
    override set it.

    Empty string ``category=""`` is the "uncategorized" sentinel - it
    selects rows where the resolved category is NULL (no override and
    no rule match). This is what the SKILL.md `pf-query list --category ""`
    invocation relies on; a literal `category = ""` predicate would
    return nothing because neither `tx_category.category` nor
    `category_overrides.category` is ever stored as an empty string.
    """
    sources = discover_sources(conn)
    union = build_tx_union_sql(sources)
    if union is None:
        return []
    where, params = _tx_filters(
        from_ts=from_ts,
        to_ts=to_ts,
        account_id=account_id,
        bank=bank,
        currency_code=currency_code,
    )
    if category is not None:
        if category == "":
            where.append(f"{CATEGORY_EXPR} IS NULL")
        else:
            where.append(f"{CATEGORY_EXPR} = ?")
            params.append(category)
    where_sql = ("\nWHERE " + " AND ".join(where)) if where else ""
    sql = (
        f"SELECT {TX_COLUMNS_SQL}, {CATEGORY_EXPR} AS category "
        f"FROM (\n{union}\n) AS tx "
        f"{CATEGORY_JOIN_SQL}"
        f"{where_sql} "
        f"ORDER BY tx.ts DESC, tx.id "
        f"LIMIT ? OFFSET ?"
    )
    rows = conn.execute(sql, [*params, int(limit), int(offset)])
    return [row_to_transaction(r) for r in rows]


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
    where, params = _tx_filters(
        from_ts=from_ts,
        to_ts=to_ts,
        account_id=account_id,
        bank=bank,
        currency_code=currency_code,
    )
    sql = (
        f"SELECT {key_expr} AS key, tx.currency_code, "
        f"SUM(tx.amount_minor) AS total_minor, "
        f"COUNT(*) AS tx_count "
        f"FROM (\n{union}\n) AS tx "
        f"{CATEGORY_JOIN_SQL} "
        f"WHERE {' AND '.join(where)} "
        # Repeat the expression rather than refer to the alias for
        # SQLite < 3.38 compatibility (no GROUP BY alias).
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


def summarize_uncategorized(
    conn: sqlite3.Connection,
    *,
    from_ts: int | None = None,
    to_ts: int | None = None,
    group_by: str = "description",
    account_id: str | None = None,
    bank: str | None = None,
    currency_code: int | None = None,
) -> list[dict[str, Any]]:
    """Cluster uncategorized transactions (resolved category IS NULL)
    by ``group_by`` and return per-cluster count + sum.

    Designed for the categorize-skill Step 2 workflow: ``pf-query
    list --category ""`` returns raw rows; this groups them so the
    user sees "MAISW CAR WASH x2, Portmone x3, ..." without piping
    through jq. Pure read-side aggregation - it does not modify the
    DB and does not consult the rules tables (only the
    already-categorized state in ``tx_category`` / ``category_overrides``).

    ``from_ts`` / ``to_ts`` are both optional - omit for "all time"
    (the typical case when triaging the leftover uncategorized pile).

    Output shape::

        [{"key": "MAISW CAR WASH",
          "currency_code": 980,
          "tx_count": 2,
          "total_minor": -14000}, ...]

    Sorted by ``tx_count`` desc then ``key`` asc. ``key`` is ``None``
    when the grouping column has NULL values - e.g. uncategorized rows
    without a description if grouping by description.
    """
    if group_by not in _UNCATEGORIZED_GROUP_BY_EXPRESSIONS:
        raise ValueError(
            f"unsupported group_by={group_by!r}; "
            f"valid values: {sorted(_UNCATEGORIZED_GROUP_BY_EXPRESSIONS.keys())}"
        )
    key_expr = _UNCATEGORIZED_GROUP_BY_EXPRESSIONS[group_by]
    sources = discover_sources(conn)
    union = build_tx_union_sql(sources)
    if union is None:
        return []
    where, params = _tx_filters(
        from_ts=from_ts,
        to_ts=to_ts,
        account_id=account_id,
        bank=bank,
        currency_code=currency_code,
    )
    where.append(f"{CATEGORY_EXPR} IS NULL")
    sql = (
        f"SELECT {key_expr} AS key, tx.currency_code, "
        f"COUNT(*) AS tx_count, "
        f"SUM(tx.amount_minor) AS total_minor "
        f"FROM (\n{union}\n) AS tx "
        f"{CATEGORY_JOIN_SQL} "
        f"WHERE {' AND '.join(where)} "
        f"GROUP BY {key_expr}, tx.currency_code "
        f"ORDER BY tx_count DESC, key ASC"
    )
    rows = conn.execute(sql, params)
    return [
        {
            "key": r[0],
            "currency_code": int(r[1]),
            "tx_count": int(r[2]),
            "total_minor": int(r[3] or 0),
        }
        for r in rows
    ]


def list_categories(conn: sqlite3.Connection) -> list[dict[str, Any]]:
    """Return every category currently assigned to at least one
    transaction, with the count of transactions resolving to it.

    Resolution follows the same precedence as ``get_transactions``: an
    override beats a rule-assigned category. So a transaction whose
    rule-assigned category is ``A`` but is overridden to ``B`` counts
    toward ``B`` only.

    Result shape::

        [{"category": "Food", "tx_count": 42},
         {"category": "Gifts", "tx_count": 3},
         ...]

    Sorted by ``tx_count`` desc, then ``category`` asc for stable
    ordering when counts tie. Does NOT include categories that exist
    only as patterns in the rule tables but have never matched a
    transaction - the goal is "what taxonomy is already in use", which
    is more useful when picking a name for a new rule than the full
    seed set (which can be enumerated via ``pf-rules list`` instead).
    """
    sql = (
        "SELECT category, COUNT(*) AS tx_count FROM ("
        "  SELECT COALESCE(o.category, c.category) AS category "
        "  FROM (SELECT tx_id FROM tx_category "
        "        UNION "
        "        SELECT tx_id FROM category_overrides) AS ids "
        "  LEFT JOIN tx_category c ON c.tx_id = ids.tx_id "
        "  LEFT JOIN category_overrides o ON o.tx_id = ids.tx_id"
        ") WHERE category IS NOT NULL "
        "GROUP BY category "
        "ORDER BY tx_count DESC, category ASC"
    )
    rows = conn.execute(sql)
    return [{"category": r[0], "tx_count": int(r[1])} for r in rows]


def find_transactions(
    conn: sqlite3.Connection,
    *,
    query: str,
    limit: int = 100,
) -> list[Transaction]:
    """Free-text LIKE search across ``description`` and ``counterparty``.

    Case-insensitive substring match - the user types "glovo" or
    "GLOVO" and gets every Glovo charge. Returns up to ``limit`` rows
    ordered by most recent first.

    ``%`` and ``_`` inside the user input are escaped (backslash) so a
    literal underscore in a description doesn't degenerate into "match
    any character". The ``ESCAPE`` clause makes the escape explicit.
    """
    text = (query or "").strip()
    if not text:
        raise ValueError("find_transactions: query must be non-empty")
    sources = discover_sources(conn)
    union = build_tx_union_sql(sources)
    if union is None:
        return []
    escaped = text.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    pattern = f"%{escaped}%"
    sql = (
        f"SELECT {TX_COLUMNS_SQL}, {CATEGORY_EXPR} AS category "
        f"FROM (\n{union}\n) AS tx "
        f"{CATEGORY_JOIN_SQL} "
        "WHERE (LOWER(COALESCE(tx.description, '')) LIKE LOWER(?) ESCAPE '\\' "
        "       OR LOWER(COALESCE(tx.counterparty, '')) LIKE LOWER(?) ESCAPE '\\') "
        "ORDER BY tx.ts DESC, tx.id "
        "LIMIT ?"
    )
    rows = conn.execute(sql, [pattern, pattern, int(limit)])
    return [row_to_transaction(r) for r in rows]


def _tx_filters(
    *,
    from_ts: int | None,
    to_ts: int | None,
    account_id: str | None,
    bank: str | None,
    currency_code: int | None,
) -> tuple[list[str], list[Any]]:
    """Build a WHERE-fragment list + bound-parameter list for the
    transactions UNION view. ``None`` values are dropped so the caller
    can pass them straight through to skip a dimension."""
    where: list[str] = []
    params: list[Any] = []
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


def row_to_transaction(row: Sequence[Any]) -> Transaction:
    """Project a 14-column sqlite3 row (``TX_COLUMNS_SQL`` + resolved
    category as the 14th element) to ``Transaction``. Public so
    ``reports.py`` reuses the same projection for its top/uncategorized
    transaction lists without duplicating the field handling."""
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
