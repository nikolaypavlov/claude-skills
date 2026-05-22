"""Shared fixtures: synthetic mono_* / privat_* tables in a tmp SQLite
DB so the tests don't depend on installing the ingest plugins.

The schemas mirror the ones actually created by monobank-mcp and
privat24-skill (per ``docs/transactions-schema.md``). The seed
transactions are deterministic and small so test_view_builder /
test_queries / test_report_bundle can assert on exact counts.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest


def _mk_mono_tables(conn: sqlite3.Connection) -> None:
    conn.executescript(
        """
        CREATE TABLE mono_accounts (
            account_id    TEXT PRIMARY KEY,
            iban          TEXT,
            type          TEXT,
            currency_code INTEGER NOT NULL,
            masked_pan    TEXT,
            label         TEXT,
            opened_at     INTEGER
        );
        CREATE TABLE mono_transactions (
            id                TEXT PRIMARY KEY,
            account_id        TEXT NOT NULL,
            ts                INTEGER NOT NULL,
            amount_minor      INTEGER NOT NULL,
            currency_code     INTEGER NOT NULL,
            op_amount_minor   INTEGER,
            op_currency_code  INTEGER,
            mcc               INTEGER,
            description       TEXT,
            counterparty      TEXT,
            balance_minor     INTEGER,
            cashback_minor    INTEGER,
            raw_json          TEXT NOT NULL,
            imported_at       INTEGER NOT NULL,
            import_run_id     INTEGER NOT NULL
        );
        CREATE TABLE mono_sync_state (
            account_id        TEXT PRIMARY KEY,
            last_completed_ts INTEGER NOT NULL,
            last_sync_at      INTEGER NOT NULL
        );
        """
    )


def _mk_privat_tables(conn: sqlite3.Connection) -> None:
    conn.executescript(
        """
        CREATE TABLE privat_accounts (
            account_id    TEXT PRIMARY KEY,
            iban          TEXT,
            type          TEXT,
            currency_code INTEGER NOT NULL,
            masked_pan    TEXT,
            label         TEXT,
            opened_at     INTEGER
        );
        CREATE TABLE privat_transactions (
            id                TEXT PRIMARY KEY,
            account_id        TEXT NOT NULL,
            ts                INTEGER NOT NULL,
            amount_minor      INTEGER NOT NULL,
            currency_code     INTEGER NOT NULL,
            op_amount_minor   INTEGER,
            op_currency_code  INTEGER,
            mcc               INTEGER,
            description       TEXT,
            counterparty      TEXT,
            balance_minor     INTEGER,
            raw_json          TEXT NOT NULL,
            imported_at       INTEGER NOT NULL,
            import_run_id     INTEGER NOT NULL
        );
        """
    )


def _seed_mono(conn: sqlite3.Connection) -> None:
    conn.execute(
        "INSERT INTO mono_accounts VALUES ('mono_acc_1', 'UA111', 'black', 980, '4444****', 'Mono UAH', NULL)"
    )
    rows = [
        ("mono_t1", "mono_acc_1", 1_700_000_000, -25000, 980, None, None, 5814, "Coffee shop", "Aroma Kava", 1_000_000, 0),
        ("mono_t2", "mono_acc_1", 1_700_001_000, -150000, 980, None, None, 5411, "Grocery shop", "Silpo", 850_000, 0),
        ("mono_t3", "mono_acc_1", 1_700_002_000, 500000, 980, None, None, None, "Salary", "Employer LLC", 1_350_000, 0),
    ]
    conn.executemany(
        "INSERT INTO mono_transactions VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, '{}', 1700100000, 1)",
        rows,
    )
    conn.execute(
        "INSERT INTO mono_sync_state VALUES ('mono_acc_1', 1700050000, 1700100000)"
    )


def _seed_privat(conn: sqlite3.Connection) -> None:
    conn.execute(
        "INSERT INTO privat_accounts VALUES ('privat_acc_1', 'UA222', NULL, 980, '5555****', NULL, NULL)"
    )
    rows = [
        ("privat_h_1", "privat_acc_1", 1_700_010_000, -33333, 980, None, None, None, "Privat shop", None, 50_000),
        ("privat_h_2", "privat_acc_1", 1_700_011_000, -50000, 980, -1429, 978, None, "EUR transfer", None, 0),
    ]
    conn.executemany(
        "INSERT INTO privat_transactions VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, '{}', 1700100000, 1)",
        rows,
    )


@pytest.fixture
def empty_db(tmp_path: Path) -> Path:
    """Empty DB - no bank tables at all, no pf_* tables."""
    db = tmp_path / "data.db"
    db.parent.mkdir(parents=True, exist_ok=True)
    return db


@pytest.fixture
def mono_only_db(tmp_path: Path) -> Path:
    """Only mono_* present."""
    db = tmp_path / "data.db"
    conn = sqlite3.connect(db)
    try:
        _mk_mono_tables(conn)
        _seed_mono(conn)
        conn.commit()
    finally:
        conn.close()
    return db


@pytest.fixture
def privat_only_db(tmp_path: Path) -> Path:
    """Only privat_* present."""
    db = tmp_path / "data.db"
    conn = sqlite3.connect(db)
    try:
        _mk_privat_tables(conn)
        _seed_privat(conn)
        conn.commit()
    finally:
        conn.close()
    return db


@pytest.fixture
def both_banks_db(tmp_path: Path) -> Path:
    """Both mono_* and privat_* present."""
    db = tmp_path / "data.db"
    conn = sqlite3.connect(db)
    try:
        _mk_mono_tables(conn)
        _mk_privat_tables(conn)
        _seed_mono(conn)
        _seed_privat(conn)
        conn.commit()
    finally:
        conn.close()
    return db
