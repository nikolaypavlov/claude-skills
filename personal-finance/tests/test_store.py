"""pf_* schema bring-up + atomic migration tests."""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from pf_skill.common import store
from pf_skill.common.store import (
    EXPECTED_PF_SCHEMA_VERSION,
    _split_statements,
    ensure_pf_schema,
    open_db,
    schema_version,
)


def test_open_db_brings_up_schema(empty_db: Path) -> None:
    conn = open_db(empty_db)
    tables = {
        r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
    }
    assert {
        "pf_schema_version",
        "categorization_rules",
        "tx_category",
        "category_overrides",
    }.issubset(tables)
    assert schema_version(conn) == EXPECTED_PF_SCHEMA_VERSION


def test_rerun_is_idempotent(empty_db: Path) -> None:
    """Re-running ``ensure_pf_schema`` must not re-apply migrations
    that already shipped: the row count must equal the number of
    distinct applied versions, not double on each call."""
    conn = open_db(empty_db)
    ensure_pf_schema(conn)
    ensure_pf_schema(conn)
    n = conn.execute("SELECT COUNT(*) FROM pf_schema_version").fetchone()[0]
    assert n == EXPECTED_PF_SCHEMA_VERSION
    # Spot-check the version row itself is unique per version.
    distinct = conn.execute(
        "SELECT COUNT(DISTINCT version) FROM pf_schema_version"
    ).fetchone()[0]
    assert distinct == EXPECTED_PF_SCHEMA_VERSION


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


def test_split_statements_handles_begin_end_block() -> None:
    """A CREATE TRIGGER body has its own ``;`` between statements
    inside ``BEGIN ... END``; those must not be treated as top-level
    statement terminators."""
    sql = (
        "CREATE TABLE t (a INT);\n"
        "CREATE TRIGGER tr BEFORE UPDATE ON t\n"
        "BEGIN\n"
        "    SELECT 1;\n"
        "    SELECT 2;\n"
        "END;\n"
        "INSERT INTO t VALUES (1);\n"
    )
    stmts = _split_statements(sql)
    assert len(stmts) == 3, f"expected 3 statements, got {len(stmts)}: {stmts}"
    assert stmts[0].startswith("CREATE TABLE")
    assert stmts[1].startswith("CREATE TRIGGER")
    assert "BEGIN" in stmts[1] and "END" in stmts[1]
    assert stmts[2].startswith("INSERT INTO")


def test_split_statements_handles_semicolon_in_string_literal() -> None:
    """``;`` inside a single-quoted string is data, not a separator.
    Doubled single quotes inside the string keep the scanner inside
    the string."""
    sql = (
        "INSERT INTO t VALUES ('hello; world');\n"
        "INSERT INTO t VALUES ('it''s; fine');\n"
    )
    stmts = _split_statements(sql)
    assert len(stmts) == 2, stmts
    assert "hello; world" in stmts[0]
    assert "it''s; fine" in stmts[1]


def test_split_statements_does_not_mistake_identifier_for_begin() -> None:
    """Whole-word keyword detection: ``begin_at`` is an identifier, not
    a BEGIN block opener."""
    sql = "CREATE TABLE t (begin_at INTEGER, end_at INTEGER);\n"
    stmts = _split_statements(sql)
    assert len(stmts) == 1, stmts
    assert "begin_at" in stmts[0]


def test_migration_rolls_back_on_failure(
    empty_db: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Inject a broken migration script and assert no pf_* DDL leaks.

    Key bits:
    - The bad statement is terminated with ``;`` so the splitter emits
      it as its own statement (without the terminator the splitter
      would fuse it with the following INSERT, and the test would not
      exercise whether the *INSERT* into ``pf_schema_version`` rolls
      back too).
    - After the failure, we assert both ``sqlite_master`` is clean AND
      ``schema_version(conn) == 0``. The latter catches a regression
      where the INSERT lands in autocommit mode.
    """
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
    # Match production: open the conn in autocommit mode so the
    # explicit BEGIN/COMMIT in ensure_pf_schema is the sole tx
    # boundary, same as `store.open_db`.
    conn.isolation_level = None
    try:
        conn.execute("PRAGMA foreign_keys = ON")
        with pytest.raises(sqlite3.OperationalError):
            ensure_pf_schema(conn)
        leaked = conn.execute(
            "SELECT COUNT(*) FROM sqlite_master "
            "WHERE name IN ('pf_schema_version', 'pf_test_a')"
        ).fetchone()[0]
        assert leaked == 0, "partial DDL leaked - atomicity broken"
        assert schema_version(conn) == 0, "version row leaked - bootstrap not in tx"
    finally:
        conn.close()


def test_default_db_path_honours_env(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("MONOBANK_MCP_DATA_DIR", str(tmp_path))
    assert store.default_db_path() == tmp_path / "data.db"


def test_default_db_path_falls_back_to_home(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("MONOBANK_MCP_DATA_DIR", raising=False)
    p = store.default_db_path()
    assert p.name == "data.db"
    assert p.parent.name == "finances"
