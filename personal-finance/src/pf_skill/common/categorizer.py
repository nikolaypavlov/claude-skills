"""Categorizer pass: walk uncategorized transactions, write
``tx_category`` rows for those that match a rule. Also imports
``overrides.local.yaml`` into ``category_overrides`` so user pins
survive across pulls.

The whole pass runs inside one explicit BEGIN/COMMIT - same atomicity
contract as the migration applier in ``store.py``. A crash mid-pass
rolls back every row; ``INSERT OR IGNORE`` on ``tx_category`` (PK on
``tx_id``) keeps the rerun idempotent.
"""

from __future__ import annotations

import sqlite3
import time
from pathlib import Path
from typing import Any

from .queries import (
    CATEGORY_EXPR,
    CATEGORY_JOIN_SQL,
    TX_COLUMNS_SQL,
)
from .rules import Rule, first_match, load_all_rules, load_overrides
from .view import build_tx_union_sql, discover_sources

VALID_SCOPES: tuple[str, ...] = ("all", "last-n-days")


def apply_rules(
    conn: sqlite3.Connection,
    *,
    scope: str = "all",
    n_days: int = 30,
    data_dir: Path | None = None,
    now: int | None = None,
) -> dict[str, Any]:
    """Run a full categorizer pass over the uncategorized transactions in
    ``scope``.

    ``scope`` is ``"all"`` (no time filter) or ``"last-n-days"`` (tx.ts
    >= now - n_days * 86400). Returns a dict with::

        {
          "categorized_count": int,    # rule-matched, written to tx_category
          "no_match_count":    int,    # left uncategorized this pass
          "overrides_applied": int,    # rows UPSERTed into category_overrides
          "active_rules":      int,    # rules considered (after enabled filter)
          "scope": { "scope": str, "from_ts": int|None, "to_ts": int|None },
        }

    ``data_dir`` defaults to ``default_db_path().parent`` so
    ``$DATA_DIR/rules/overrides.local.yaml`` is found out of the box.
    Pass an explicit dir from tests.
    """
    if scope not in VALID_SCOPES:
        raise ValueError(f"unsupported scope={scope!r}; valid values: {list(VALID_SCOPES)}")
    if scope == "last-n-days" and n_days <= 0:
        raise ValueError("--n must be a positive integer when scope=last-n-days")

    now_ts = int(now) if now is not None else int(time.time())
    from_ts: int | None = None
    if scope == "last-n-days":
        from_ts = now_ts - int(n_days) * 86_400

    sources = discover_sources(conn)
    union = build_tx_union_sql(sources)
    rules = load_all_rules(conn, data_dir=data_dir)
    enabled_rules = [r for r in rules if r.enabled]

    # Overrides land regardless of whether there is a transaction source
    # right now - the user may have pinned a tx that arrives in a later
    # ingest. category_overrides is just keyed by tx_id.
    overrides_applied = _apply_overrides(conn, data_dir=data_dir, now_ts=now_ts)

    if union is None:
        return _summary(
            categorized=0,
            no_match=0,
            overrides=overrides_applied,
            active_rules=len(enabled_rules),
            scope=scope,
            from_ts=from_ts,
            to_ts=None,
        )

    pending = _fetch_uncategorized(conn, union, from_ts=from_ts)
    categorized = 0
    no_match = 0
    conn.execute("BEGIN")
    try:
        for row in pending:
            rule = first_match(
                enabled_rules,
                mcc=row["mcc"],
                description=row["description"],
                counterparty=row["counterparty"],
            )
            if rule is None:
                no_match += 1
                continue
            _insert_category(conn, row["id"], rule, now_ts=now_ts)
            categorized += 1
        conn.commit()
    except Exception:
        conn.rollback()
        raise

    return _summary(
        categorized=categorized,
        no_match=no_match,
        overrides=overrides_applied,
        active_rules=len(enabled_rules),
        scope=scope,
        from_ts=from_ts,
        to_ts=None,
    )


def _apply_overrides(
    conn: sqlite3.Connection,
    *,
    data_dir: Path | None,
    now_ts: int,
) -> int:
    """UPSERT every override.local.yaml entry into category_overrides.

    ``INSERT OR REPLACE`` so the file is authoritative: editing the YAML
    and re-running pf-categorize updates the row to the latest value.
    Wrapped in its own BEGIN/COMMIT to keep the override import atomic
    independently of the rule pass below.
    """
    overrides = load_overrides(data_dir)
    if not overrides:
        return 0
    conn.execute("BEGIN")
    try:
        for entry in overrides:
            conn.execute(
                "INSERT OR REPLACE INTO category_overrides "
                "(tx_id, category, note, set_at) VALUES (?, ?, ?, ?)",
                (entry["tx_id"], entry["category"], entry.get("note"), now_ts),
            )
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    return len(overrides)


def _fetch_uncategorized(
    conn: sqlite3.Connection,
    union: str,
    *,
    from_ts: int | None,
) -> list[dict[str, Any]]:
    """Pull every uncategorized transaction in scope as plain dicts.

    Uses ``CATEGORY_EXPR IS NULL`` after the LEFT JOIN so both
    ``tx_category`` matches and ``category_overrides`` pins exclude the
    row. The ``id`` / ``mcc`` / ``description`` / ``counterparty``
    columns are all the categorizer needs.
    """
    where = [f"{CATEGORY_EXPR} IS NULL"]
    params: list[Any] = []
    if from_ts is not None:
        where.append("tx.ts >= ?")
        params.append(int(from_ts))
    sql = (
        f"SELECT {TX_COLUMNS_SQL} "
        f"FROM (\n{union}\n) AS tx "
        f"{CATEGORY_JOIN_SQL} "
        f"WHERE {' AND '.join(where)} "
        f"ORDER BY tx.ts DESC, tx.id"
    )
    rows = conn.execute(sql, params).fetchall()
    return [
        {
            "id": r[0],
            "bank": r[1],
            "account_id": r[2],
            "ts": int(r[3]),
            "amount_minor": int(r[4]),
            "currency_code": int(r[5]),
            "mcc": int(r[8]) if r[8] is not None else None,
            "description": r[9],
            "counterparty": r[10],
        }
        for r in rows
    ]


def _insert_category(
    conn: sqlite3.Connection,
    tx_id: str,
    rule: Rule,
    *,
    now_ts: int,
) -> None:
    """Insert a ``tx_category`` row for ``tx_id`` based on ``rule``.

    ``INSERT OR IGNORE`` so a concurrent pass that already wrote this
    tx (or a stale "uncategorized" snapshot) does not error out. The
    PK on ``tx_id`` means the first writer wins, which is fine - the
    later writer would have produced the same category anyway under
    sane rule sets.
    """
    conn.execute(
        "INSERT OR IGNORE INTO tx_category "
        "(tx_id, category, rule_id, set_at, set_by) VALUES (?, ?, ?, ?, ?)",
        (tx_id, rule.category, rule.rule_id, now_ts, "rule"),
    )


def _summary(
    *,
    categorized: int,
    no_match: int,
    overrides: int,
    active_rules: int,
    scope: str,
    from_ts: int | None,
    to_ts: int | None,
) -> dict[str, Any]:
    return {
        "categorized_count": categorized,
        "no_match_count": no_match,
        "overrides_applied": overrides,
        "active_rules": active_rules,
        "scope": {"scope": scope, "from_ts": from_ts, "to_ts": to_ts},
    }


def preview_rule(
    conn: sqlite3.Connection,
    *,
    match_field: str,
    pattern: str,
    category: str,
    limit_sample: int = 5,
) -> dict[str, Any]:
    """Probe how many existing transactions a candidate rule would touch.

    Used by ``pf-rules add`` to surface the "would affect N rows" preview
    the design doc spec calls for. Counts ALL matching transactions in
    the store (not scoped) but returns at most ``limit_sample`` example
    rows. Does NOT write to ``tx_category`` - that is the explicit job
    of ``pf-rules apply``.

    Returns::

        {
          "match_field": str,
          "pattern": str,
          "category": str,
          "would_affect_count": int,
          "sample": list[Transaction],
        }
    """
    sources = discover_sources(conn)
    union = build_tx_union_sql(sources)
    if union is None:
        return {
            "match_field": match_field,
            "pattern": pattern,
            "category": category,
            "would_affect_count": 0,
            "sample": [],
        }
    candidate = Rule(
        priority=DEFAULT_PRIORITY_FOR_FIELD[match_field],
        match_field=match_field,
        pattern=pattern,
        category=category,
        source="preview",
    )
    rows = _fetch_uncategorized(conn, union, from_ts=None)
    matched = [
        row
        for row in rows
        if candidate.matches(
            mcc=row["mcc"],
            description=row["description"],
            counterparty=row["counterparty"],
        )
    ]
    sample = matched[: max(0, int(limit_sample))]
    return {
        "match_field": match_field,
        "pattern": pattern,
        "category": category,
        "would_affect_count": len(matched),
        "sample": sample,
    }


def apply_rule_by_id(
    conn: sqlite3.Connection,
    *,
    rule_id: int,
    dry_run: bool = False,
    now: int | None = None,
) -> dict[str, Any]:
    """Retroactively apply a single DB rule to every matching
    uncategorized transaction.

    ``dry_run=True`` reports the count + sample without writing. Used by
    ``pf-rules apply`` after the user yeses the preview from ``add``.

    Returns the same shape as ``preview_rule`` plus an ``applied`` int
    when ``dry_run=False`` (rows actually inserted into ``tx_category``).
    """
    row = conn.execute(
        "SELECT id, priority, match_field, pattern, category, enabled "
        "FROM categorization_rules WHERE id = ?",
        (int(rule_id),),
    ).fetchone()
    if row is None:
        raise ValueError(f"no rule with id={rule_id}")
    rule = Rule(
        priority=int(row[1]),
        match_field=str(row[2]),
        pattern=str(row[3]),
        category=str(row[4]),
        source="db",
        rule_id=int(row[0]),
        enabled=bool(row[5]),
    )
    sources = discover_sources(conn)
    union = build_tx_union_sql(sources)
    if union is None:
        return {
            "rule_id": rule.rule_id,
            "category": rule.category,
            "matched_count": 0,
            "applied": 0,
            "dry_run": dry_run,
            "sample": [],
        }

    pending = _fetch_uncategorized(conn, union, from_ts=None)
    matched = [
        row
        for row in pending
        if rule.matches(
            mcc=row["mcc"],
            description=row["description"],
            counterparty=row["counterparty"],
        )
    ]

    applied = 0
    if not dry_run and matched:
        now_ts = int(now) if now is not None else int(time.time())
        conn.execute("BEGIN")
        try:
            for row in matched:
                _insert_category(conn, row["id"], rule, now_ts=now_ts)
                applied += 1
            conn.commit()
        except Exception:
            conn.rollback()
            raise

    return {
        "rule_id": rule.rule_id,
        "category": rule.category,
        "matched_count": len(matched),
        "applied": applied,
        "dry_run": dry_run,
        "sample": matched[:5],
    }


# Mapping used by ``preview_rule`` so the default priority for a
# would-be rule matches the source it would land in once persisted.
DEFAULT_PRIORITY_FOR_FIELD: dict[str, int] = {
    "mcc": 300,
    "counterparty": 200,
    "description": 100,
}
