"""Migration semantics: idempotent, single version row, atomic apply."""

from __future__ import annotations

import sqlite3
from pathlib import Path

from privat24_import.core.store import (
    EXPECTED_PRIVAT_SCHEMA_VERSION,
    ensure_privat_schema,
    open_db,
)


def test_fresh_db_lands_at_expected_version(tmp_path: Path) -> None:
    db = tmp_path / "data.db"
    conn = open_db(db)
    v = conn.execute("SELECT MAX(version) FROM privat_schema_version").fetchone()[0]
    assert v == EXPECTED_PRIVAT_SCHEMA_VERSION


def test_rerun_does_not_duplicate_version_row(tmp_path: Path) -> None:
    db = tmp_path / "data.db"
    conn = open_db(db)
    # Hit the migration path several more times - the connection is the
    # same, but the inner ensure_privat_schema must short-circuit cleanly.
    ensure_privat_schema(conn)
    ensure_privat_schema(conn)
    n = conn.execute("SELECT COUNT(*) FROM privat_schema_version").fetchone()[0]
    assert n == 1


def test_reopen_persists_schema(tmp_path: Path) -> None:
    db = tmp_path / "data.db"
    open_db(db).close()
    conn = sqlite3.connect(db)
    conn.execute("PRAGMA foreign_keys = ON")
    tables = sorted(
        r[0]
        for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name LIKE 'privat_%'"
        )
    )
    assert tables == [
        "privat_accounts",
        "privat_import_runs",
        "privat_schema_version",
        "privat_transactions",
    ]
