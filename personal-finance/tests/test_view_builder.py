"""Runtime discovery + UNION ALL builder tests."""

from __future__ import annotations

import sqlite3
from pathlib import Path

from pf_skill.common import store
from pf_skill.common.view import (
    build_accounts_union_sql,
    build_tx_union_sql,
    discover_sources,
)


def _open(db: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(db)
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def test_empty_db_yields_no_sources(empty_db: Path) -> None:
    conn = _open(empty_db)
    sources = discover_sources(conn)
    assert sources.tx_banks == ()
    assert sources.account_banks == ()
    assert sources.has_any_tx() is False
    assert build_tx_union_sql(sources) is None
    assert build_accounts_union_sql(sources) is None


def test_mono_only(mono_only_db: Path) -> None:
    conn = _open(mono_only_db)
    sources = discover_sources(conn)
    assert sources.tx_banks == ("mono",)
    sql = build_tx_union_sql(sources)
    assert sql is not None
    # No UNION ALL when there's only one leg.
    assert "UNION ALL" not in sql
    rows = list(conn.execute(f"SELECT bank, COUNT(*) FROM ({sql}) GROUP BY bank"))
    assert rows == [("mono", 3)]


def test_privat_only(privat_only_db: Path) -> None:
    conn = _open(privat_only_db)
    sources = discover_sources(conn)
    assert sources.tx_banks == ("privat",)
    sql = build_tx_union_sql(sources)
    assert sql is not None
    rows = list(conn.execute(f"SELECT bank, COUNT(*) FROM ({sql}) GROUP BY bank"))
    assert rows == [("privat", 2)]


def test_both_banks_union(both_banks_db: Path) -> None:
    conn = _open(both_banks_db)
    sources = discover_sources(conn)
    assert sources.tx_banks == ("mono", "privat")
    sql = build_tx_union_sql(sources)
    assert sql is not None
    assert "UNION ALL" in sql
    rows = list(
        conn.execute(f"SELECT bank, COUNT(*) FROM ({sql}) GROUP BY bank ORDER BY bank")
    )
    assert rows == [("mono", 3), ("privat", 2)]


def test_accounts_union(both_banks_db: Path) -> None:
    conn = _open(both_banks_db)
    sources = discover_sources(conn)
    sql = build_accounts_union_sql(sources)
    assert sql is not None
    rows = list(
        conn.execute(f"SELECT bank, COUNT(*) FROM ({sql}) GROUP BY bank ORDER BY bank")
    )
    assert rows == [("mono", 1), ("privat", 1)]


def test_does_not_match_unrelated_tables(tmp_path: Path) -> None:
    """Tables whose names happen to contain 'transactions' but don't
    follow the ``<bank>_transactions`` convention must NOT be picked
    up. The regex requires a single alphanumeric prefix segment
    (no embedded underscores) followed by ``_transactions``."""
    db = tmp_path / "data.db"
    conn = sqlite3.connect(db)
    try:
        conn.executescript(
            """
            CREATE TABLE my_other_transactions (id TEXT);  -- prefix has '_'
            CREATE TABLE transactions_log (id TEXT);       -- wrong suffix
            CREATE TABLE foo (id TEXT);
            CREATE TABLE revolut_transactions (id TEXT);   -- legitimate
            """
        )
        conn.commit()
        sources = discover_sources(conn)
        assert sources.tx_banks == ("revolut",)
    finally:
        conn.close()


def test_pf_schema_bringup_does_not_inject_a_fake_bank(empty_db: Path) -> None:
    """Bringing up pf_* tables must not look like a `<bank>_*` source."""
    conn = store.open_db(empty_db)
    sources = discover_sources(conn)
    assert sources.tx_banks == ()
    assert sources.account_banks == ()
