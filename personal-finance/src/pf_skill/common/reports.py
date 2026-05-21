"""Bundle construction for the ``pf-report`` CLI entry.

Lives separately from ``queries.py`` because the bundle is a richer
shape than any single query - it stitches together accounts, the
period, currencies, transactions or monthly buckets, top-N highlights,
uncategorized transactions, sync freshness, and the optional
previous-period comparison.

Auto-switch between full-dump and bucketed mode lives here too: short
periods (<= ``FULL_DUMP_THRESHOLD_DAYS``) get every transaction inline
so Claude can do its own grouping; longer periods get pre-aggregated
monthly buckets plus the largest-by-absolute-amount transactions for
narrative colour.
"""

from __future__ import annotations

import sqlite3
from typing import Any, TypedDict

from .queries import get_transactions, list_accounts
from .view import build_tx_union_sql, discover_sources

# Periods up to this many days inline every transaction in the bundle.
# Beyond this, we switch to monthly_buckets + top_transactions + the
# always-included uncategorized_transactions. 90 days is the design-doc
# default and matches what a typical "last quarter" review needs.
FULL_DUMP_THRESHOLD_DAYS = 90

# Cap on highlighted transactions in bucketed mode. 100 is enough for
# Claude to spot "Recurring", "Anomalies", and "Top counterparties"
# narrative beats without blowing the context window.
TOP_TRANSACTIONS_LIMIT = 100


class PeriodSummary(TypedDict):
    in_minor: int
    out_minor: int
    tx_count: int


class CurrencyComparison(TypedDict):
    currency_code: int
    current: PeriodSummary
    previous: PeriodSummary


def build_report_bundle(
    conn: sqlite3.Connection,
    *,
    from_ts: int,
    to_ts: int,
    account_id: str | None = None,
    bank: str | None = None,
    comparison: str | None = None,
) -> dict[str, Any]:
    """Assemble the report bundle for the given period.

    ``comparison`` may be ``"previous-period"`` (symmetrical window
    immediately before ``[from_ts, to_ts)``) or ``None`` (omit the
    ``comparison`` key entirely).

    On an empty store (no ingest plugin installed) returns a bundle
    with empty ``accounts`` / ``transactions`` and a ``warning`` field
    so the caller can surface it instead of pretending the period has
    no activity.
    """
    sources = discover_sources(conn)
    accounts = list_accounts(conn)
    period_days = max(1, (to_ts - from_ts) // 86_400)
    mode = "full" if period_days <= FULL_DUMP_THRESHOLD_DAYS else "bucketed"

    bundle: dict[str, Any] = {
        "ok": True,
        "period": {
            "from_ts": from_ts,
            "to_ts": to_ts,
            "tz_hint": "Europe/Kyiv",
        },
        "mode": mode,
        "accounts": accounts,
        "currencies_seen": [],
        "active_rules_count": 0,
        "uncategorized_count": 0,
        "last_sync_ts": _last_sync_ts_per_bank(conn, sources.tx_banks),
    }

    if not sources.has_any_tx():
        bundle["warning"] = (
            "no transaction sources detected - install at least one ingest "
            "plugin (monobank-mcp or privat24-skill)"
        )
        return bundle

    common_filters = {
        "from_ts": from_ts,
        "to_ts": to_ts,
        "account_id": account_id,
        "bank": bank,
    }

    bundle["currencies_seen"] = _currencies_seen(conn, sources, **common_filters)
    bundle["active_rules_count"] = _active_rules_count(conn)
    bundle["uncategorized_count"] = _uncategorized_count(
        conn, sources, **common_filters
    )

    if mode == "full":
        bundle["transactions"] = get_transactions(
            conn,
            from_ts=from_ts,
            to_ts=to_ts,
            account_id=account_id,
            bank=bank,
            limit=10_000,
        )
    else:
        bundle["monthly_buckets"] = _monthly_buckets(
            conn, sources, **common_filters
        )
        bundle["top_transactions"] = _top_transactions(
            conn, sources, **common_filters, limit=TOP_TRANSACTIONS_LIMIT
        )

    bundle["uncategorized_transactions"] = _uncategorized_transactions(
        conn, sources, **common_filters
    )

    if comparison == "previous-period":
        bundle["comparison"] = _build_comparison(
            conn,
            sources,
            from_ts=from_ts,
            to_ts=to_ts,
            account_id=account_id,
            bank=bank,
        )

    return bundle


# --- private helpers ---------------------------------------------------------


def _table_exists(conn: sqlite3.Connection, name: str) -> bool:
    row = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",
        (name,),
    ).fetchone()
    return row is not None


def _last_sync_ts_per_bank(
    conn: sqlite3.Connection, tx_banks: tuple[str, ...]
) -> dict[str, int | None]:
    """Best-effort freshness signal per detected bank.

    For ``mono``: ``MAX(last_completed_ts)`` from ``mono_sync_state``
    when present (that's the API cursor, true "we have pulled through
    this timestamp" signal). For every other bank including ``privat``:
    ``MAX(imported_at)`` from ``<bank>_transactions`` (the closest
    approximation - when the last data landed in the store).
    """
    result: dict[str, int | None] = {}
    for bank in tx_banks:
        state_table = f"{bank}_sync_state"
        if _table_exists(conn, state_table):
            row = conn.execute(
                f"SELECT MAX(last_completed_ts) FROM {state_table}"
            ).fetchone()
        else:
            tx_table = f'"{bank}_transactions"'
            row = conn.execute(f"SELECT MAX(imported_at) FROM {tx_table}").fetchone()
        result[bank] = int(row[0]) if row and row[0] is not None else None
    return result


def _active_rules_count(conn: sqlite3.Connection) -> int:
    row = conn.execute(
        "SELECT COUNT(*) FROM categorization_rules WHERE enabled = 1"
    ).fetchone()
    return int(row[0]) if row else 0


def _currencies_seen(
    conn: sqlite3.Connection,
    sources: Any,
    *,
    from_ts: int,
    to_ts: int,
    account_id: str | None,
    bank: str | None,
) -> list[int]:
    union = build_tx_union_sql(sources)
    if union is None:
        return []
    where, params = _period_where(from_ts, to_ts, account_id, bank)
    rows = conn.execute(
        f"SELECT DISTINCT tx.currency_code FROM (\n{union}\n) AS tx "
        f"WHERE {' AND '.join(where)} "
        f"ORDER BY tx.currency_code",
        params,
    )
    return [int(r[0]) for r in rows]


def _uncategorized_count(
    conn: sqlite3.Connection,
    sources: Any,
    *,
    from_ts: int,
    to_ts: int,
    account_id: str | None,
    bank: str | None,
) -> int:
    union = build_tx_union_sql(sources)
    if union is None:
        return 0
    where, params = _period_where(from_ts, to_ts, account_id, bank)
    row = conn.execute(
        f"SELECT COUNT(*) FROM (\n{union}\n) AS tx "
        f"LEFT JOIN tx_category ON tx_category.tx_id = tx.id "
        f"LEFT JOIN category_overrides ON category_overrides.tx_id = tx.id "
        f"WHERE {' AND '.join(where)} "
        f"AND COALESCE(category_overrides.category, tx_category.category) IS NULL",
        params,
    ).fetchone()
    return int(row[0]) if row else 0


def _monthly_buckets(
    conn: sqlite3.Connection,
    sources: Any,
    *,
    from_ts: int,
    to_ts: int,
    account_id: str | None,
    bank: str | None,
) -> list[dict[str, Any]]:
    union = build_tx_union_sql(sources)
    if union is None:
        return []
    where, params = _period_where(from_ts, to_ts, account_id, bank)
    category_expr = "COALESCE(category_overrides.category, tx_category.category)"
    rows = conn.execute(
        f"SELECT strftime('%Y-%m', tx.ts, 'unixepoch') AS year_month, "
        f"  {category_expr} AS category, "
        f"  tx.currency_code, "
        f"  SUM(tx.amount_minor) AS total_minor, "
        f"  COUNT(*) AS tx_count "
        f"FROM (\n{union}\n) AS tx "
        f"LEFT JOIN tx_category ON tx_category.tx_id = tx.id "
        f"LEFT JOIN category_overrides ON category_overrides.tx_id = tx.id "
        f"WHERE {' AND '.join(where)} "
        # Repeat the expression rather than refer to the alias for
        # SQLite < 3.38 compatibility (no GROUP BY alias).
        f"GROUP BY year_month, {category_expr}, tx.currency_code "
        f"ORDER BY year_month, total_minor",
        params,
    )
    return [
        {
            "year_month": r[0],
            "category": r[1] if r[1] is not None else "(uncategorized)",
            "currency_code": int(r[2]),
            "total_minor": int(r[3] or 0),
            "tx_count": int(r[4]),
        }
        for r in rows
    ]


def _top_transactions(
    conn: sqlite3.Connection,
    sources: Any,
    *,
    from_ts: int,
    to_ts: int,
    account_id: str | None,
    bank: str | None,
    limit: int,
) -> list[dict[str, Any]]:
    union = build_tx_union_sql(sources)
    if union is None:
        return []
    where, params = _period_where(from_ts, to_ts, account_id, bank)
    rows = conn.execute(
        "SELECT tx.id, tx.bank, tx.account_id, tx.ts, tx.amount_minor, "
        "tx.currency_code, tx.op_amount_minor, tx.op_currency_code, "
        "tx.mcc, tx.description, tx.counterparty, tx.balance_minor, "
        "tx.imported_at, "
        "COALESCE(category_overrides.category, tx_category.category) AS category "
        f"FROM (\n{union}\n) AS tx "
        "LEFT JOIN tx_category ON tx_category.tx_id = tx.id "
        "LEFT JOIN category_overrides ON category_overrides.tx_id = tx.id "
        f"WHERE {' AND '.join(where)} "
        "ORDER BY ABS(tx.amount_minor) DESC, tx.ts DESC "
        "LIMIT ?",
        [*params, int(limit)],
    )
    return [_row_to_tx_dict(r) for r in rows]


def _uncategorized_transactions(
    conn: sqlite3.Connection,
    sources: Any,
    *,
    from_ts: int,
    to_ts: int,
    account_id: str | None,
    bank: str | None,
) -> list[dict[str, Any]]:
    union = build_tx_union_sql(sources)
    if union is None:
        return []
    where, params = _period_where(from_ts, to_ts, account_id, bank)
    rows = conn.execute(
        "SELECT tx.id, tx.bank, tx.account_id, tx.ts, tx.amount_minor, "
        "tx.currency_code, tx.op_amount_minor, tx.op_currency_code, "
        "tx.mcc, tx.description, tx.counterparty, tx.balance_minor, "
        "tx.imported_at, "
        "NULL AS category "
        f"FROM (\n{union}\n) AS tx "
        "LEFT JOIN tx_category ON tx_category.tx_id = tx.id "
        "LEFT JOIN category_overrides ON category_overrides.tx_id = tx.id "
        f"WHERE {' AND '.join(where)} "
        "AND COALESCE(category_overrides.category, tx_category.category) IS NULL "
        "ORDER BY ABS(tx.amount_minor) DESC, tx.ts DESC",
        params,
    )
    return [_row_to_tx_dict(r) for r in rows]


def _build_comparison(
    conn: sqlite3.Connection,
    sources: Any,
    *,
    from_ts: int,
    to_ts: int,
    account_id: str | None,
    bank: str | None,
) -> dict[str, Any]:
    span = to_ts - from_ts
    prev_to = from_ts
    prev_from = from_ts - span
    return {
        "previous_period": {"from_ts": prev_from, "to_ts": prev_to},
        "per_currency": _per_currency_comparison(
            conn,
            sources,
            current=(from_ts, to_ts),
            previous=(prev_from, prev_to),
            account_id=account_id,
            bank=bank,
        ),
    }


def _per_currency_comparison(
    conn: sqlite3.Connection,
    sources: Any,
    *,
    current: tuple[int, int],
    previous: tuple[int, int],
    account_id: str | None,
    bank: str | None,
) -> list[CurrencyComparison]:
    cur = _in_out_per_currency(
        conn, sources, *current, account_id=account_id, bank=bank
    )
    prev = _in_out_per_currency(
        conn, sources, *previous, account_id=account_id, bank=bank
    )
    currencies = sorted(set(cur.keys()) | set(prev.keys()))
    zero = PeriodSummary(in_minor=0, out_minor=0, tx_count=0)
    return [
        CurrencyComparison(
            currency_code=ccy,
            current=cur.get(ccy, zero),
            previous=prev.get(ccy, zero),
        )
        for ccy in currencies
    ]


def _in_out_per_currency(
    conn: sqlite3.Connection,
    sources: Any,
    from_ts: int,
    to_ts: int,
    *,
    account_id: str | None,
    bank: str | None,
) -> dict[int, PeriodSummary]:
    union = build_tx_union_sql(sources)
    if union is None:
        return {}
    where, params = _period_where(from_ts, to_ts, account_id, bank)
    rows = conn.execute(
        f"SELECT tx.currency_code, "
        f"  SUM(CASE WHEN tx.amount_minor > 0 THEN tx.amount_minor ELSE 0 END) AS in_minor, "
        f"  SUM(CASE WHEN tx.amount_minor < 0 THEN tx.amount_minor ELSE 0 END) AS out_minor, "
        f"  COUNT(*) AS tx_count "
        f"FROM (\n{union}\n) AS tx "
        f"WHERE {' AND '.join(where)} "
        f"GROUP BY tx.currency_code",
        params,
    )
    return {
        int(r[0]): PeriodSummary(
            in_minor=int(r[1] or 0),
            out_minor=int(r[2] or 0),
            tx_count=int(r[3]),
        )
        for r in rows
    }


def _period_where(
    from_ts: int,
    to_ts: int,
    account_id: str | None,
    bank: str | None,
) -> tuple[list[str], list[Any]]:
    where = ["tx.ts >= ?", "tx.ts < ?"]
    params: list[Any] = [int(from_ts), int(to_ts)]
    if account_id is not None:
        where.append("tx.account_id = ?")
        params.append(account_id)
    if bank is not None:
        where.append("tx.bank = ?")
        params.append(bank)
    return where, params


def _row_to_tx_dict(row: Any) -> dict[str, Any]:
    """Project a 14-column sqlite3 row to the same dict shape
    ``Transaction`` carries, but as a plain dict to avoid the TypedDict
    indirection here (the bundle ships these to stdout via json.dumps).
    """
    return {
        "id": row[0],
        "bank": row[1],
        "account_id": row[2],
        "ts": int(row[3]),
        "amount_minor": int(row[4]),
        "currency_code": int(row[5]),
        "op_amount_minor": int(row[6]) if row[6] is not None else None,
        "op_currency_code": int(row[7]) if row[7] is not None else None,
        "mcc": int(row[8]) if row[8] is not None else None,
        "description": row[9],
        "counterparty": row[10],
        "balance_minor": int(row[11]) if row[11] is not None else None,
        "imported_at": int(row[12]),
        "category": row[13],
    }
