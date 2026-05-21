"""SQLite store + schema bring-up for the ``pf_*`` table group.

Mirrors the atomicity contract used by ``monobank-mcp`` and
``privat24-skill``:
- PRAGMAs (``journal_mode``, ``foreign_keys``, ``busy_timeout``) are
  set once per connection BEFORE migrations run.
- Each pending migration runs inside an explicit ``BEGIN`` / ``COMMIT``
  built from individual ``conn.execute`` calls. Python's
  ``sqlite3.Connection.executescript`` is deliberately NOT used - it
  issues an implicit ``COMMIT`` first, which would silently close the
  explicit ``BEGIN`` and run the migration in autocommit mode.
- The version-tracker table itself is created INSIDE the migration
  transaction (the ``CREATE TABLE IF NOT EXISTS pf_schema_version``
  lives in the SQL file, not in Python), so a crash mid-apply rolls
  back the tracker too.
"""

from __future__ import annotations

import os
import sqlite3
from importlib import resources
from pathlib import Path

EXPECTED_PF_SCHEMA_VERSION = 1

# Apply in order. Each entry: (version, filename inside pf_server.schema).
_MIGRATION_FILES: list[tuple[int, str]] = [(1, "pf_001_initial.sql")]


def default_db_path() -> Path:
    """Return the shared SQLite path.

    Honours ``MONOBANK_MCP_DATA_DIR`` for consistency with the ingest
    plugins (they expose the same env override). Falls back to
    ``~/finances/data.db``.
    """
    env = os.environ.get("MONOBANK_MCP_DATA_DIR")
    base = Path(env).expanduser() if env else Path.home() / "finances"
    return base / "data.db"


def open_db(path: str | Path | None = None) -> sqlite3.Connection:
    """Open the shared store and ensure the pf_* schema is current.

    Idempotent and safe to call from multiple plugins; the migrations
    use ``IF NOT EXISTS`` guards and the PRAGMAs are repeated-application
    safe.
    """
    target = Path(path).expanduser() if path else default_db_path()
    target.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(target)
    conn.execute("PRAGMA journal_mode = WAL")
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA busy_timeout = 5000")
    ensure_pf_schema(conn)
    return conn


def ensure_pf_schema(conn: sqlite3.Connection) -> None:
    """Apply pending pf_* migrations atomically.

    The bootstrap CREATE TABLE for ``pf_schema_version`` lives inside
    the migration SQL itself, so the version tracker is part of the
    same atomic transaction as the rest of the pf_* DDL. On a fresh DB
    the SELECT raises ``OperationalError`` which we catch and treat as
    ``applied = 0``.
    """
    try:
        applied = conn.execute(
            "SELECT COALESCE(MAX(version), 0) FROM pf_schema_version"
        ).fetchone()[0]
    except sqlite3.OperationalError:
        applied = 0
    for version, filename in _MIGRATION_FILES:
        if version <= applied:
            continue
        sql = _load_migration_sql(filename)
        statements = _split_statements(sql)
        conn.execute("BEGIN")
        try:
            for stmt in statements:
                conn.execute(stmt)
            conn.commit()
        except Exception:
            conn.rollback()
            raise


def _load_migration_sql(filename: str) -> str:
    return (
        resources.files("pf_server.schema")
        .joinpath(filename)
        .read_text(encoding="utf-8")
    )


def _split_statements(sql: str) -> list[str]:
    """Split a SQL script into individual statements on top-level ``;``.

    Strips ``-- ...`` line comments first so a ``;`` inside an inline
    comment (e.g. ``-- regex; for mcc``) doesn't fragment the statement
    list. Does NOT understand block comments (``/* ... */``) or string
    literals containing ``;`` - if a future migration introduces
    either, swap this for ``sqlparse.split(sql)``.
    """
    cleaned_lines: list[str] = []
    for line in sql.splitlines():
        idx = line.find("--")
        cleaned_lines.append(line if idx < 0 else line[:idx])
    cleaned = "\n".join(cleaned_lines)
    return [s.strip() for s in cleaned.split(";") if s.strip()]


def schema_version(conn: sqlite3.Connection) -> int:
    """Return the highest applied pf_* migration version, or 0."""
    try:
        row = conn.execute(
            "SELECT COALESCE(MAX(version), 0) FROM pf_schema_version"
        ).fetchone()
    except sqlite3.OperationalError:
        return 0
    return int(row[0]) if row else 0
