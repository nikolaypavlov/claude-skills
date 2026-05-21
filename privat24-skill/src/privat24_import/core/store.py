"""SQLite store for the ``privat_*`` schema group.

Mirrors the monobank-mcp atomicity contract:
- PRAGMA defaults set once per connection BEFORE migrations run.
- Each migration applied inside an explicit ``BEGIN`` / ``COMMIT``.
- INSERTs and the sync-state-equivalent updates (here just import_runs
  finalisation) live in their own transactions; a kill mid-import never
  leaves a half-committed batch.
"""

from __future__ import annotations

import json
import sqlite3
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

# Repo layout: src/privat24_import/lib/store.py -> ../../../schema/
SCHEMA_DIR = Path(__file__).resolve().parent.parent.parent.parent / "schema"

EXPECTED_PRIVAT_SCHEMA_VERSION = 1

# Apply in order. Each entry maps version -> SQL file content.
MIGRATIONS: list[tuple[int, str]] = [
    (1, (SCHEMA_DIR / "privat_001_initial.sql").read_text(encoding="utf-8")),
]


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
    raw: dict


def open_db(path: str | Path) -> sqlite3.Connection:
    """Open the shared SQLite store and ensure the privat schema is current.

    Idempotent. Safe to call from multiple plugins; PRAGMAs and migrations
    use ``IF NOT EXISTS`` guards.
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
    """Apply pending privat_* migrations. Each runs in its own transaction
    so a crash mid-apply rolls back cleanly."""
    conn.execute(
        "CREATE TABLE IF NOT EXISTS privat_schema_version ("
        "    version INTEGER PRIMARY KEY,"
        "    applied_at INTEGER NOT NULL"
        ")"
    )
    applied = conn.execute(
        "SELECT COALESCE(MAX(version), 0) FROM privat_schema_version"
    ).fetchone()[0]
    for version, sql in MIGRATIONS:
        if version <= applied:
            continue
        # sqlite3's connection-level transactions wrap by default, but
        # executescript() commits implicitly. We use explicit BEGIN/COMMIT
        # to get atomicity over a multi-statement script.
        conn.execute("BEGIN")
        try:
            conn.executescript(sql)
            conn.commit()
        except Exception:
            conn.rollback()
            raise


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


def upsert_account(
    conn: sqlite3.Connection,
    *,
    account_id: str,
    iban: str | None,
    account_type: str | None,
    currency_code: int,
    masked_pan: str | None,
    label: str | None = None,
) -> None:
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
        (account_id, iban, account_type, currency_code, masked_pan, label),
    )
    conn.commit()


@dataclass
class InsertOutcome:
    rows_inserted: int = 0
    rows_skipped: int = 0


def insert_transactions(
    conn: sqlite3.Connection,
    *,
    run_id: int,
    txs: Iterable[Tx],
) -> InsertOutcome:
    """Insert a batch of transactions atomically. INSERT OR IGNORE means
    rows already present (by id) bump rows_skipped rather than rows_inserted."""
    out = InsertOutcome()
    imported_at = int(time.time())
    conn.execute("BEGIN")
    try:
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
                out.rows_skipped += 1
            else:
                out.rows_inserted += 1
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    return out


def count_transactions(conn: sqlite3.Connection) -> int:
    return conn.execute("SELECT COUNT(*) FROM privat_transactions").fetchone()[0]
