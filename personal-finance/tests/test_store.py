"""pf_* schema bring-up + atomic migration tests."""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from pf_server import store
from pf_server.store import (
    EXPECTED_PF_SCHEMA_VERSION,
    _split_statements,
    ensure_pf_schema,
    open_db,
    schema_version,
)


def test_open_db_brings_up_schema(empty_db: Path) -> None:
    conn = open_db(empty_db)
    tables = {
        r[0]
        for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
    }
    assert {
        "pf_schema_version",
        "categorization_rules",
        "tx_category",
        "category_overrides",
    }.issubset(tables)
    assert schema_version(conn) == EXPECTED_PF_SCHEMA_VERSION


def test_rerun_is_idempotent(empty_db: Path) -> None:
    conn = open_db(empty_db)
    ensure_pf_schema(conn)
    ensure_pf_schema(conn)
    n = conn.execute("SELECT COUNT(*) FROM pf_schema_version").fetchone()[0]
    assert n == 1


def test_split_statements_ignores_semicolons_in_comments() -> None:
    """The naive split was bitten by SQL comments containing ``;``.
    The fix strips ``--`` comment tails before splitting."""
    sql = (
        "CREATE TABLE t (\n"
        "    a TEXT,    -- format; allows colons\n"
        "    b INTEGER  -- another; comment\n"
        ");\n"
        "INSERT INTO t VALUES ('x', 1);"
    )
    stmts = _split_statements(sql)
    assert len(stmts) == 2, f"expected 2 statements, got {len(stmts)}: {stmts}"
    assert stmts[0].startswith("CREATE TABLE")
    assert stmts[1].startswith("INSERT INTO")


def test_migration_rolls_back_on_failure(empty_db: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Inject a broken migration script and assert no pf_* DDL leaks."""
    monkeypatch.setattr(
        store,
        "_load_migration_sql",
        lambda _name: (
            "CREATE TABLE pf_schema_version ("
            "  version INTEGER PRIMARY KEY, applied_at INTEGER NOT NULL);"
            "CREATE TABLE pf_test_a (id INTEGER);"
            "THIS IS NOT VALID SQL;"
            "INSERT INTO pf_schema_version VALUES (1, 0);"
        ),
    )
    conn = sqlite3.connect(empty_db)
    try:
        conn.execute("PRAGMA foreign_keys = ON")
        with pytest.raises(sqlite3.OperationalError):
            ensure_pf_schema(conn)
        leaked = conn.execute(
            "SELECT COUNT(*) FROM sqlite_master "
            "WHERE name IN ('pf_schema_version', 'pf_test_a')"
        ).fetchone()[0]
        assert leaked == 0, "partial DDL leaked - atomicity broken"
    finally:
        conn.close()


def test_default_db_path_honours_env(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("MONOBANK_MCP_DATA_DIR", str(tmp_path))
    assert store.default_db_path() == tmp_path / "data.db"


def test_default_db_path_falls_back_to_home(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("MONOBANK_MCP_DATA_DIR", raising=False)
    p = store.default_db_path()
    assert p.name == "data.db"
    assert p.parent.name == "finances"
