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
#
# IMPORTANT: ``currency_code`` is sourced from ``acc.currency_code`` (the
# ACCOUNT'S currency), NOT from ``tx.currency_code`` (the OPERATION
# currency that ingest plugins store for cross-currency rows). That way
# the public ``currency_code`` field is always denominationally consistent
# with ``amount_minor`` - both are in the account currency. The
# operation currency is still available per-row via ``op_currency_code``
# / ``op_amount_minor`` when the merchant charged in something else.
# Every query that uses this SELECT-list MUST include the accounts JOIN
# from ``accounts_join_sql`` in its FROM clause - otherwise SQLite will
# fail with "no such column: acc.currency_code".
TX_COLUMNS_SQL = (
    "tx.id, tx.bank, tx.account_id, tx.ts, tx.amount_minor, "
    "acc.currency_code, tx.op_amount_minor, tx.op_currency_code, "
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
#
# ``currency`` resolves to the ACCOUNT currency (``acc.currency_code``),
# not the operation currency: a Patreon charge on a UAH black card is
# stored with ``tx.currency_code = 840`` (USD - the merchant's billing
# currency), but ``amount_minor`` is in UAH kopecks. Grouping by the
# operation currency would file that row under USD even though no USD
# actually left the account. See the comment on ``TX_COLUMNS_SQL``.
_GROUP_BY_EXPRESSIONS: dict[str, str] = {
    "category": CATEGORY_EXPR,
    "mcc": "tx.mcc",
    "counterparty": "tx.counterparty",
    "currency": "acc.currency_code",
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


def accounts_join_sql(sources: DiscoveredSources) -> str:
    """JOIN clause that exposes ``acc.currency_code`` (the account
    currency, i.e. the denomination of ``amount_minor``) per tx row.

    Strict INNER JOIN: a transaction whose ``account_id`` has no row in
    the discovered ``<bank>_accounts`` UNION is dropped from the result
    rather than silently NULL-bucketed. In practice every ingest plugin
    owns both ``<bank>_transactions`` and ``<bank>_accounts`` per the
    cross-plugin contract, so a missing match means the store is
    half-synced (or a future bank-prefix added tx without accounts) -
    failing loud is the right reaction.

    Returns an empty string if no accounts tables are discovered; the
    caller should short-circuit on ``build_tx_union_sql() is None``
    before calling, so this branch is defensive only.
    """
    accounts_union = build_accounts_union_sql(sources)
    if accounts_union is None:
        return ""
    return f"JOIN (\n{accounts_union}\n) AS acc ON acc.account_id = tx.account_id "


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


# Friendly display names for Monobank's account `type` values. The
# ingest stores the raw API type ('black', 'fop', 'diia', 'eAid',
# 'madeInUkraine') and never a label, so the presentation layer maps
# them. Types that exist in several currencies get a currency suffix
# (Black-UAH, FOP-USD); single-currency products stay bare (Diia, eAid)
# to match how the user names them. Unknown types fall back to a
# title-cased form so a new Mono product still renders sensibly.
_MONO_TYPE_NAMES: dict[str, str] = {
    "black": "Black",
    "fop": "FOP",
    "diia": "Diia",
    "eaid": "eAid",
    "madeinukraine": "madeInUkraine",
}
_MULTI_CURRENCY_TYPES: frozenset[str] = frozenset({"black", "fop"})


def account_display_name(
    *, type_: str | None, currency_alpha: str | None, label: str | None
) -> str | None:
    """Human name for an account. A stored ``label`` always wins; else
    derive from the Mono ``type`` (+ currency suffix for multi-currency
    products). Returns ``None`` only when there is nothing to go on."""
    if label:
        return label
    if not type_:
        return None
    key = type_.lower()
    base = _MONO_TYPE_NAMES.get(key, type_.capitalize())
    if key in _MULTI_CURRENCY_TYPES and currency_alpha:
        return f"{base}-{currency_alpha}"
    return base


def _account_balance_for(
    conn: sqlite3.Connection, *, bank: str, account_id: str
) -> tuple[int | None, int | None, int | None, str]:
    """Resolve (balance_minor, credit_limit_minor, balance_synced_at,
    source) for one account.

    Prefers the authoritative per-account balance stored on
    ``<bank>_accounts`` (monobank-mcp >= 0.3 persists ``balance_minor`` /
    ``credit_limit_minor`` from client-info). This sidesteps the
    same-timestamp transfer-pair ambiguity that makes the transaction
    tail an unreliable balance source for pass-through accounts.

    Falls back to the latest transaction's ``balance_minor`` for banks
    whose account table carries no balance column (e.g. privat, imported
    from XLSX). ``source`` is ``"account"``, ``"transaction"``, or
    ``"none"`` so the caller can flag stale / missing data.

    ``bank`` is a regex-validated prefix from ``discover_sources`` and is
    safe to interpolate into the table identifier.
    """
    acc_cols = {r[1] for r in conn.execute(f'PRAGMA table_info("{bank}_accounts")')}
    if "balance_minor" in acc_cols:
        credit_expr = "credit_limit_minor" if "credit_limit_minor" in acc_cols else "NULL"
        synced_expr = "balance_synced_at" if "balance_synced_at" in acc_cols else "NULL"
        row = conn.execute(
            f"SELECT balance_minor, {credit_expr}, {synced_expr} "
            f'FROM "{bank}_accounts" WHERE account_id = ?',
            (account_id,),
        ).fetchone()
        if row is not None and row[0] is not None:
            return (int(row[0]), _opt_int(row[1]), _opt_int(row[2]), "account")

    # Fallback: newest transaction that carries a running balance.
    tx_cols = {r[1] for r in conn.execute(f'PRAGMA table_info("{bank}_transactions")')}
    if "balance_minor" in tx_cols:
        row = conn.execute(
            f'SELECT balance_minor FROM "{bank}_transactions" '
            f"WHERE account_id = ? AND balance_minor IS NOT NULL "
            f"ORDER BY ts DESC, id DESC LIMIT 1",
            (account_id,),
        ).fetchone()
        if row is not None and row[0] is not None:
            return (int(row[0]), None, None, "transaction")
    return (None, None, None, "none")


def _opt_int(value: Any) -> int | None:
    return int(value) if value is not None else None


def account_balances(
    conn: sqlite3.Connection,
    *,
    sources: DiscoveredSources | None = None,
) -> list[dict[str, Any]]:
    """Current balance and real funds for every discovered account.

    ``real_funds_minor = balance_minor - credit_limit_minor`` (a credit
    line is baked into the reported balance, so only the excess is the
    user's own money; a balance below the limit means debt). Accounts
    with no resolvable balance report ``balance_minor = None`` and
    ``balance_source = "none"`` so the caller can surface them rather
    than silently dropping them from a coverage total.

    One dict per account, ordered by currency then name. Currency is
    kept per-account; callers sum WITHIN a currency, never across.
    """
    from .currencies import alpha_for

    if sources is None:
        sources = discover_sources(conn)
    accounts = list_accounts(conn, sources=sources)
    out: list[dict[str, Any]] = []
    for acc in accounts:
        balance, credit, synced_at, source = _account_balance_for(
            conn, bank=acc["bank"], account_id=acc["account_id"]
        )
        real = balance - (credit or 0) if balance is not None else None
        alpha = alpha_for(acc["currency_code"])
        out.append(
            {
                "account_id": acc["account_id"],
                "bank": acc["bank"],
                "type": acc["type"],
                "name": account_display_name(
                    type_=acc["type"], currency_alpha=alpha, label=acc["label"]
                ),
                "currency_code": acc["currency_code"],
                "currency": alpha or str(acc["currency_code"]),
                "balance_minor": balance,
                "credit_limit_minor": credit,
                "real_funds_minor": real,
                "balance_synced_at": synced_at,
                "balance_source": source,
            }
        )
    out.sort(key=lambda r: (r["currency"], r["name"] or r["account_id"]))
    return out


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
    accounts_join = accounts_join_sql(sources)
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
        f"{accounts_join}"
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
    accounts_join = accounts_join_sql(sources)
    where, params = _tx_filters(
        from_ts=from_ts,
        to_ts=to_ts,
        account_id=account_id,
        bank=bank,
        currency_code=currency_code,
    )
    sql = (
        f"SELECT {key_expr} AS key, acc.currency_code, "
        f"SUM(tx.amount_minor) AS total_minor, "
        f"COUNT(*) AS tx_count "
        f"FROM (\n{union}\n) AS tx "
        f"{accounts_join}"
        f"{CATEGORY_JOIN_SQL} "
        f"WHERE {' AND '.join(where)} "
        # Repeat the expression rather than refer to the alias for
        # SQLite < 3.38 compatibility (no GROUP BY alias).
        f"GROUP BY {key_expr}, acc.currency_code "
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
    accounts_join = accounts_join_sql(sources)
    where, params = _tx_filters(
        from_ts=from_ts,
        to_ts=to_ts,
        account_id=account_id,
        bank=bank,
        currency_code=currency_code,
    )
    where.append(f"{CATEGORY_EXPR} IS NULL")
    sql = (
        f"SELECT {key_expr} AS key, acc.currency_code, "
        f"COUNT(*) AS tx_count, "
        f"SUM(tx.amount_minor) AS total_minor "
        f"FROM (\n{union}\n) AS tx "
        f"{accounts_join}"
        f"{CATEGORY_JOIN_SQL} "
        f"WHERE {' AND '.join(where)} "
        f"GROUP BY {key_expr}, acc.currency_code "
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


def list_categories(
    conn: sqlite3.Connection,
    *,
    include_declared: bool = False,
) -> list[dict[str, Any]]:
    """Return every category currently assigned to at least one
    transaction, with the count of transactions resolving to it.

    Resolution follows the same precedence as ``get_transactions``: an
    override beats a rule-assigned category. So a transaction whose
    rule-assigned category is ``A`` but is overridden to ``B`` counts
    toward ``B`` only.

    Result shape::

        [{"category": "Food", "tx_count": 42, "declared": false},
         {"category": "Gifts", "tx_count": 3, "declared": false},
         ...]

    Sorted by ``tx_count`` desc, then ``category`` asc for stable
    ordering when counts tie. Does NOT include categories that exist
    only as patterns in the rule tables but have never matched a
    transaction - the goal is "what taxonomy is already in use", which
    is more useful when picking a name for a new rule than the full
    seed set (which can be enumerated via ``pf-rules list`` instead).

    ``include_declared``: when True, also surface entries from
    ``category_registry`` that have no matching transactions yet. They
    appear with ``tx_count = 0`` and ``declared = True`` so callers
    (notably ``pf-budget`` validation) can treat "declared-but-unused"
    as legitimate without conflating it with "I made up a typo".
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
    in_use_rows = list(conn.execute(sql))
    results = [{"category": r[0], "tx_count": int(r[1]), "declared": False} for r in in_use_rows]
    if not include_declared:
        return results
    in_use_names = {r["category"] for r in results}
    try:
        declared_rows = list(
            conn.execute("SELECT category FROM category_registry ORDER BY category ASC")
        )
    except sqlite3.OperationalError as exc:
        # ``category_registry`` was added in migration v2. Surface a
        # clear error if the table is missing rather than silently
        # ignoring --include-declared.
        if "no such table" not in str(exc).lower():
            raise
        return results
    for (name,) in declared_rows:
        if name in in_use_names:
            continue
        results.append({"category": name, "tx_count": 0, "declared": True})
    return results


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
    accounts_join = accounts_join_sql(sources)
    escaped = text.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    pattern = f"%{escaped}%"
    sql = (
        f"SELECT {TX_COLUMNS_SQL}, {CATEGORY_EXPR} AS category "
        f"FROM (\n{union}\n) AS tx "
        f"{accounts_join}"
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
        # Filter by ACCOUNT currency, not operation currency: a UAH-card
        # / USD-merchant row has ``tx.currency_code = 840`` even though
        # the user thinks of it as a UAH charge (that is what
        # ``amount_minor`` is denominated in). Filtering on
        # ``tx.currency_code`` would silently drop these rows from
        # ``--currency UAH``.
        where.append("acc.currency_code = ?")
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
