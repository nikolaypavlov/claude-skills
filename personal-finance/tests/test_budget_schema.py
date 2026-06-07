"""pf_002_budget migration - schema bring-up and trigger tests."""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from pf_skill.common.store import (
    EXPECTED_PF_SCHEMA_VERSION,
    open_db,
    schema_version,
)


def test_budget_tables_present_after_open(empty_db: Path) -> None:
    conn = open_db(empty_db)
    tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    assert {
        "category_registry",
        "budget",
        "budget_line",
        "budget_import_run",
    }.issubset(tables)
    assert schema_version(conn) == EXPECTED_PF_SCHEMA_VERSION
    assert EXPECTED_PF_SCHEMA_VERSION >= 2


def test_budget_constraints_enforced(empty_db: Path) -> None:
    """The CHECK constraints from the migration should reject obvious
    bad inputs at INSERT time rather than letting them rot in the DB."""
    conn = open_db(empty_db)
    conn.isolation_level = None
    # period must be YYYY-MM
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(
            "INSERT INTO budget (period, currency_code, created_at) VALUES (?, ?, ?)",
            ("2026-6", 980, 1700000000),
        )
    # status must be in the allowed set
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(
            "INSERT INTO budget (period, currency_code, status, created_at) VALUES (?, ?, ?, ?)",
            ("2026-06", 980, "frozen", 1700000000),
        )

    # Insert a valid budget so we can test budget_line.kind constraint
    conn.execute(
        "INSERT INTO budget (period, currency_code, created_at) VALUES (?, ?, ?)",
        ("2026-06", 980, 1700000000),
    )
    budget_id = conn.execute(
        "SELECT id FROM budget WHERE period = '2026-06' AND currency_code = 980"
    ).fetchone()[0]

    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(
            "INSERT INTO budget_line (budget_id, category, amount_minor, kind) VALUES (?, ?, ?, ?)",
            (budget_id, "Test", -1000, "weird"),
        )
    # category_registry.declared_via constraint
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(
            "INSERT INTO category_registry (category, declared_at, declared_via) VALUES (?, ?, ?)",
            ("Test", 1700000000, "magic"),
        )


def test_budget_period_currency_unique(empty_db: Path) -> None:
    conn = open_db(empty_db)
    conn.isolation_level = None
    conn.execute(
        "INSERT INTO budget (period, currency_code, created_at) VALUES (?, ?, ?)",
        ("2026-06", 980, 1700000000),
    )
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(
            "INSERT INTO budget (period, currency_code, created_at) VALUES (?, ?, ?)",
            ("2026-06", 980, 1700000001),
        )
    # Different currency is fine.
    conn.execute(
        "INSERT INTO budget (period, currency_code, created_at) VALUES (?, ?, ?)",
        ("2026-06", 840, 1700000002),
    )


def test_budget_line_cascades_on_budget_delete(empty_db: Path) -> None:
    conn = open_db(empty_db)
    conn.isolation_level = None
    conn.execute(
        "INSERT INTO budget (period, currency_code, created_at) VALUES (?, ?, ?)",
        ("2026-06", 980, 1700000000),
    )
    budget_id = conn.execute("SELECT id FROM budget WHERE period = '2026-06'").fetchone()[0]
    conn.execute(
        "INSERT INTO budget_line (budget_id, category, amount_minor, kind) VALUES (?, ?, ?, ?)",
        (budget_id, "Test", -1000, "baseline"),
    )
    conn.execute("DELETE FROM budget WHERE id = ?", (budget_id,))
    n = conn.execute(
        "SELECT COUNT(*) FROM budget_line WHERE budget_id = ?", (budget_id,)
    ).fetchone()[0]
    assert n == 0


# Closed-budget enforcement triggers ride with PR6 (close/reopen
# lifecycle). They need BEGIN/END SQL blocks that ``_split_statements``
# does not currently understand. See pf_002_budget.sql NOTE.
