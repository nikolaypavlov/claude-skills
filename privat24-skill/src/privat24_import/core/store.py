"""SQLite store for the ``privat_*`` schema group.

Atomicity contract (mirrors monobank-mcp):
- PRAGMA defaults (``journal_mode=WAL``, ``foreign_keys=ON``,
  ``busy_timeout``) are set once per connection BEFORE migrations run.
- Each migration runs inside an EXPLICIT ``BEGIN`` / ``COMMIT`` built
  from individual ``conn.execute`` calls. We deliberately do NOT use
  ``sqlite3.Connection.executescript``: per the Python stdlib docs it
  issues an implicit ``COMMIT`` first, which would silently close the
  ``BEGIN`` and run the migration in autocommit mode.
- ``insert_transactions`` accepts an optional account row that is
  upserted inside the same transaction as the INSERTs, so a crash
  mid-import never leaves a dangling account with zero transactions.
- ``start_import_run`` and ``finish_import_run`` commit independently
  so the run id is durable for error reporting even when the inner
  batch rolls back.

Resource loading:
- Migration SQL lives at ``src/privat24_import/schema/`` inside the
  package and is loaded via ``importlib.resources``, so the code works
  both in a source-tree layout and in an installed wheel.
"""

from __future__ import annotations

import json
import sqlite3
import time
from dataclasses import dataclass
from importlib import resources
from pathlib import Path
from typing import Iterable

EXPECTED_PRIVAT_SCHEMA_VERSION = 1

# Migration files in apply order. The SQL bytes are read lazily inside
# ``ensure_privat_schema`` so a missing/misplaced schema file fails when
# the migration runs (with full context) rather than at module import.
_MIGRATION_FILES: list[tuple[int, str]] = [(1, "privat_001_initial.sql")]


@dataclass(frozen=True)
class Tx:
    """In-memory transaction ready for ``insert_transactions``."""

    id: str
    account_id: str
    ts: int
    amount_minor: int
    currency_code: int
    op_amount_minor: int | None
    op_currency_code: int | None
    mcc: int | None
    description: str
    counterparty: str | None
    balance_minor: int | None
    raw: dict[str, object]


@dataclass(frozen=True)
class AccountSpec:
    """Account row to upsert atomically with a batch of transactions."""

    account_id: str
    iban: str | None
    account_type: str | None
    currency_code: int
    masked_pan: str | None
    label: str | None = None


@dataclass(frozen=True)
class InsertOutcome:
    rows_inserted: int = 0
    rows_skipped: int = 0


def open_db(path: str | Path) -> sqlite3.Connection:
    """Open the shared SQLite store and ensure the privat schema is current.

    Idempotent. Safe to call from multiple plugins; PRAGMAs and
    migrations use ``IF NOT EXISTS`` guards.
    """
    path = Path(path).expanduser()
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.execute("PRAGMA journal_mode = WAL")
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA busy_timeout = 5000")
    ensure_privat_schema(conn)
    return conn


def ensure_privat_schema(conn: sqlite3.Connection) -> None:
    """Apply pending privat_* migrations atomically.

    Each pending migration runs inside an explicit transaction built
    from individual ``conn.execute`` calls so a crash mid-apply rolls
    back cleanly. Idempotent: applied versions are skipped.
    """
    conn.execute(
        "CREATE TABLE IF NOT EXISTS privat_schema_version ("
        "    version INTEGER PRIMARY KEY,"
        "    applied_at INTEGER NOT NULL"
        ")"
    )
    applied = conn.execute(
        "SELECT COALESCE(MAX(version), 0) FROM privat_schema_version"
    ).fetchone()[0]
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
    """Read a migration file from the in-package ``schema/`` resource."""
    return (
        resources.files("privat24_import.schema")
        .joinpath(filename)
        .read_text(encoding="utf-8")
    )


def _split_statements(sql: str) -> list[str]:
    """Split a SQL script into individual statements on top-level ``;``.

    Our migration files never embed ``;`` inside string literals or
    comments, so the naive split is correct. If that assumption ever
    breaks, swap this for sqlite3's `Connection.iterdump`-style parser.
    """
    return [s.strip() for s in sql.split(";") if s.strip()]


def already_imported(conn: sqlite3.Connection, file_sha256: str) -> int | None:
    """Return the import_run id for a previously-imported file, or None."""
    row = conn.execute(
        "SELECT id FROM privat_import_runs WHERE file_sha256 = ? ORDER BY id LIMIT 1",
        (file_sha256,),
    ).fetchone()
    return row[0] if row else None


def start_import_run(
    conn: sqlite3.Connection,
    *,
    source: str,
    file_path: str | None,
    file_sha256: str | None,
) -> int:
    """Insert a new import_run row and commit immediately so the id is
    durable for error reporting even when the data-insert tx rolls back."""
    cur = conn.execute(
        "INSERT INTO privat_import_runs (source, started_at, file_path, file_sha256) "
        "VALUES (?, ?, ?, ?)",
        (source, int(time.time()), file_path, file_sha256),
    )
    conn.commit()
    assert cur.lastrowid is not None
    return cur.lastrowid


def finish_import_run(
    conn: sqlite3.Connection,
    run_id: int,
    *,
    rows_inserted: int,
    rows_skipped: int,
    error: str | None = None,
) -> None:
    conn.execute(
        "UPDATE privat_import_runs "
        "SET finished_at = ?, rows_inserted = ?, rows_skipped = ?, error = ? "
        "WHERE id = ?",
        (int(time.time()), rows_inserted, rows_skipped, error, run_id),
    )
    conn.commit()


def insert_transactions(
    conn: sqlite3.Connection,
    *,
    run_id: int,
    txs: Iterable[Tx],
    account: AccountSpec | None = None,
) -> InsertOutcome:
    """Upsert the account (if given) and insert a batch of transactions
    inside a single transaction. ``INSERT OR IGNORE`` means rows already
    present (by id) bump ``rows_skipped`` rather than ``rows_inserted``.

    Atomicity guarantee: a failure inside this call rolls back the
    account upsert AND every tx insert. A kill between the BEGIN and
    COMMIT leaves no half-applied state.
    """
    rows_inserted = 0
    rows_skipped = 0
    imported_at = int(time.time())
    conn.execute("BEGIN")
    try:
        if account is not None:
            conn.execute(
                "INSERT INTO privat_accounts "
                "    (account_id, iban, type, currency_code, masked_pan, label, opened_at) "
                "VALUES (?, ?, ?, ?, ?, ?, NULL) "
                "ON CONFLICT(account_id) DO UPDATE SET "
                "    iban = COALESCE(excluded.iban, privat_accounts.iban), "
                "    type = COALESCE(excluded.type, privat_accounts.type), "
                "    currency_code = excluded.currency_code, "
                "    masked_pan = COALESCE(excluded.masked_pan, privat_accounts.masked_pan), "
                "    label = COALESCE(excluded.label, privat_accounts.label)",
                (
                    account.account_id,
                    account.iban,
                    account.account_type,
                    account.currency_code,
                    account.masked_pan,
                    account.label,
                ),
            )
        for tx in txs:
            raw_json = json.dumps(tx.raw, ensure_ascii=False, default=str)
            cur = conn.execute(
                "INSERT OR IGNORE INTO privat_transactions "
                "(id, account_id, ts, amount_minor, currency_code, "
                " op_amount_minor, op_currency_code, mcc, description, "
                " counterparty, balance_minor, raw_json, imported_at, import_run_id) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    tx.id,
                    tx.account_id,
                    tx.ts,
                    tx.amount_minor,
                    tx.currency_code,
                    tx.op_amount_minor,
                    tx.op_currency_code,
                    tx.mcc,
                    tx.description,
                    tx.counterparty,
                    tx.balance_minor,
                    raw_json,
                    imported_at,
                    run_id,
                ),
            )
            if cur.rowcount == 0:
                rows_skipped += 1
            else:
                rows_inserted += 1
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    return InsertOutcome(rows_inserted=rows_inserted, rows_skipped=rows_skipped)


def count_transactions(conn: sqlite3.Connection) -> int:
    return conn.execute("SELECT COUNT(*) FROM privat_transactions").fetchone()[0]


def upsert_account_standalone(
    conn: sqlite3.Connection,
    account: AccountSpec,
) -> None:
    """Upsert an account row in its own transaction.

    Convenience wrapper around the upsert step embedded in
    ``insert_transactions``. Useful for callers (e.g. tests) that want
    to seed accounts independently. The atomic ingest path goes through
    ``insert_transactions(account=AccountSpec(...))`` instead.
    """
    conn.execute("BEGIN")
    try:
        conn.execute(
            "INSERT INTO privat_accounts "
            "    (account_id, iban, type, currency_code, masked_pan, label, opened_at) "
            "VALUES (?, ?, ?, ?, ?, ?, NULL) "
            "ON CONFLICT(account_id) DO UPDATE SET "
            "    iban = COALESCE(excluded.iban, privat_accounts.iban), "
            "    type = COALESCE(excluded.type, privat_accounts.type), "
            "    currency_code = excluded.currency_code, "
            "    masked_pan = COALESCE(excluded.masked_pan, privat_accounts.masked_pan), "
            "    label = COALESCE(excluded.label, privat_accounts.label)",
            (
                account.account_id,
                account.iban,
                account.account_type,
                account.currency_code,
                account.masked_pan,
                account.label,
            ),
        )
        conn.commit()
    except Exception:
        conn.rollback()
        raise
