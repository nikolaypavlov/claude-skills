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


def test_v5_rebuild_preserves_budget_line_data(empty_db: Path) -> None:
    """Regression test for the migration v5 cascade bug.

    Migration v5 rebuilds the ``budget`` table to loosen the UNIQUE
    constraint. ``budget_line`` has ``ON DELETE CASCADE`` against
    ``budget(id)``, so the ``DROP TABLE budget`` step inside the
    migration would wipe every ``budget_line`` row unless foreign
    keys are disabled for the duration of the migration. The fix
    landed in ``ensure_pf_schema``: it toggles ``PRAGMA
    foreign_keys = OFF`` around each migration's transaction. This
    test simulates the actual upgrade path by inserting data after
    v4 then triggering v5, and asserts that the lines survive.
    """
    # Apply migrations up through v4 by hand.
    conn = sqlite3.connect(empty_db)
    conn.isolation_level = None
    try:
        conn.execute("PRAGMA foreign_keys = ON")
        # Snapshot the real migration list, then truncate to v4.
        original = store._MIGRATION_FILES
        try:
            store._MIGRATION_FILES = [m for m in original if m[0] <= 4]
            ensure_pf_schema(conn)
        finally:
            store._MIGRATION_FILES = original
        # Seed a budget + child lines under the v4 schema.
        conn.execute(
            "INSERT INTO budget (period, currency_code, status, created_at) "
            "VALUES (?, ?, ?, ?)",
            ("2026-06", 980, "active", 1700000000),
        )
        budget_id = conn.execute(
            "SELECT id FROM budget WHERE period = '2026-06'"
        ).fetchone()[0]
        for category, amount in (("Test/A", -100), ("Test/B", -200), ("Test/C", -300)):
            conn.execute(
                "INSERT INTO budget_line (budget_id, category, amount_minor, kind) "
                "VALUES (?, ?, ?, ?)",
                (budget_id, category, amount, "baseline"),
            )
        before_lines = conn.execute(
            "SELECT COUNT(*) FROM budget_line"
        ).fetchone()[0]
        assert before_lines == 3
        # Now run the full migration list - v5 will rebuild the table.
        ensure_pf_schema(conn)
        after_lines = conn.execute(
            "SELECT COUNT(*) FROM budget_line WHERE budget_id = ?", (budget_id,)
        ).fetchone()[0]
        assert after_lines == 3, "v5 rebuild dropped budget_line via cascade"
        # And the new UNIQUE constraint is in place: a draft for the
        # same (period, currency) coexists with the active row.
        conn.execute(
            "INSERT INTO budget (period, currency_code, status, created_at) "
            "VALUES (?, ?, ?, ?)",
            ("2026-06", 980, "draft", 1700100000),
        )
    finally:
        conn.close()


def test_migration_runner_catches_orphan_fk(
    empty_db: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A migration that leaves a dangling FK reference must fail at
    the foreign_key_check gate after COMMIT. This regression-tests
    the safety net we added alongside disabling FK during the
    transaction."""
    bad_sql = (
        "CREATE TABLE pf_schema_version "
        "(version INTEGER PRIMARY KEY, applied_at INTEGER NOT NULL);\n"
        "CREATE TABLE parent (id INTEGER PRIMARY KEY);\n"
        "CREATE TABLE child (id INTEGER PRIMARY KEY, "
        " parent_id INTEGER NOT NULL REFERENCES parent(id));\n"
        "INSERT INTO parent (id) VALUES (1);\n"
        "INSERT INTO child (id, parent_id) VALUES (10, 1);\n"
        # The migration intentionally orphans the child: drop the parent
        # row but leave the child's reference behind. With FKs disabled
        # during the tx this INSERT/DELETE pair commits cleanly; the
        # safety net should fire afterwards.
        "DELETE FROM parent WHERE id = 1;\n"
        "INSERT INTO pf_schema_version VALUES (1, 0);\n"
    )
    monkeypatch.setattr(store, "_load_migration_sql", lambda _name: bad_sql)
    monkeypatch.setattr(store, "_MIGRATION_FILES", [(1, "bad.sql")])
    conn = sqlite3.connect(empty_db)
    conn.isolation_level = None
    try:
        conn.execute("PRAGMA foreign_keys = ON")
        with pytest.raises(sqlite3.IntegrityError, match="foreign key violations"):
            ensure_pf_schema(conn)
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
