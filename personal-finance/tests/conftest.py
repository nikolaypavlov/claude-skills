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
        (
            "mono_t1",
            "mono_acc_1",
            1_700_000_000,
            -25000,
            980,
            None,
            None,
            5814,
            "Coffee shop",
            "Aroma Kava",
            1_000_000,
            0,
        ),
        (
            "mono_t2",
            "mono_acc_1",
            1_700_001_000,
            -150000,
            980,
            None,
            None,
            5411,
            "Grocery shop",
            "Silpo",
            850_000,
            0,
        ),
        (
            "mono_t3",
            "mono_acc_1",
            1_700_002_000,
            500000,
            980,
            None,
            None,
            None,
            "Salary",
            "Employer LLC",
            1_350_000,
            0,
        ),
    ]
    conn.executemany(
        "INSERT INTO mono_transactions VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, '{}', 1700100000, 1)",
        rows,
    )
    conn.execute("INSERT INTO mono_sync_state VALUES ('mono_acc_1', 1700050000, 1700100000)")


def _seed_privat(conn: sqlite3.Connection) -> None:
    conn.execute(
        "INSERT INTO privat_accounts VALUES ('privat_acc_1', 'UA222', NULL, 980, '5555****', NULL, NULL)"
    )
    rows = [
        (
            "privat_h_1",
            "privat_acc_1",
            1_700_010_000,
            -33333,
            980,
            None,
            None,
            None,
            "Privat shop",
            None,
            50_000,
        ),
        (
            "privat_h_2",
            "privat_acc_1",
            1_700_011_000,
            -50000,
            980,
            -1429,
            978,
            None,
            "EUR transfer",
            None,
            0,
        ),
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


def _seed_mixed_currency_mono(conn: sqlite3.Connection) -> None:
    """Three mono accounts with foreign-merchant rows exercising the
    operation-vs-account currency distinction.

    Shapes mirror what Monobank's ``/personal/statement`` API returns:
    ``amount_minor`` is always in the ACCOUNT currency, ``currency_code``
    is the OPERATION currency, and ``op_amount_minor`` /
    ``op_currency_code`` are the original FX amount/code (NULL when the
    operation currency equals the account currency).
    """
    conn.executescript(
        """
        INSERT INTO mono_accounts VALUES
          ('uah_card',  'UA001', 'black', 980, '4444****', 'UAH card', NULL),
          ('usd_card',  'UA002', 'black', 840, '4444****', 'USD card', NULL),
          ('eur_jar',   'UA003', 'jar',   978, NULL,       'EUR jar',  NULL);
        """
    )
    rows = [
        # Patreon-shaped: UAH card billed for a $4.80 charge - amount_minor
        # is in UAH kopecks; currency_code = USD (operation) - this is the
        # bug exemplar.
        (
            "uah_patreon",
            "uah_card",
            1_700_000_000,
            -21232,
            840,
            -480,
            840,
            5968,
            "Patreon",
            "Patreon",
            1_000_000,
            0,
        ),
        # Apple-shaped: another UAH card / USD merchant row.
        (
            "uah_apple",
            "uah_card",
            1_700_001_000,
            -13226,
            840,
            -299,
            840,
            5816,
            "Apple",
            "Apple",
            980_000,
            0,
        ),
        # UAH card / EUR merchant - third currency to prove we group by
        # account, not operation.
        (
            "uah_eur",
            "uah_card",
            1_700_002_000,
            -50000,
            978,
            -1100,
            978,
            4789,
            "EU Train",
            None,
            920_000,
            0,
        ),
        # USD card / USD merchant - same-currency tx, op_* NULL. This is
        # the regression guard: must still bucket to USD (840).
        (
            "usd_aws",
            "usd_card",
            1_700_003_000,
            -5500,
            840,
            None,
            None,
            7372,
            "AWS",
            "Amazon",
            100_000,
            0,
        ),
        # USD card / EUR merchant - exotic but real, USD card sees an EUR
        # charge. Must bucket to USD (account).
        (
            "usd_eur",
            "usd_card",
            1_700_004_000,
            -3300,
            978,
            -3000,
            978,
            5814,
            "Cafe",
            "Cafe EU",
            95_000,
            0,
        ),
        # EUR jar / EUR transfer - same-currency, op_* NULL. Buckets EUR.
        (
            "eur_topup",
            "eur_jar",
            1_700_005_000,
            100000,
            978,
            None,
            None,
            None,
            "Topup",
            None,
            100_000,
            0,
        ),
    ]
    conn.executemany(
        "INSERT INTO mono_transactions VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, '{}', 1700100000, 1)",
        rows,
    )


@pytest.fixture
def mixed_currency_db(tmp_path: Path) -> Path:
    """Mono store with three accounts in different currencies and a
    spread of foreign-merchant rows. Used by the regression tests for
    the operation-vs-account currency fix."""
    db = tmp_path / "data.db"
    conn = sqlite3.connect(db)
    try:
        _mk_mono_tables(conn)
        _seed_mixed_currency_mono(conn)
        conn.commit()
    finally:
        conn.close()
    return db
