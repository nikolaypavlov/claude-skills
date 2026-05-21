"""Store smoke tests: schema bring-up, FK enforcement, idempotent inserts,
atomic account+tx upsert, executescript-style atomic migrations."""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest
from privat24_import.core.store import (
    AccountSpec,
    InsertOutcome,
    Tx,
    already_imported,
    ensure_privat_schema,
    finish_import_run,
    insert_transactions,
    open_db,
    start_import_run,
)


def _acc(account_id: str = "acc1") -> AccountSpec:
    return AccountSpec(
        account_id=account_id,
        iban=None,
        account_type=None,
        currency_code=980,
        masked_pan="4111 **** **** 0000",
    )


def _tx(idx: int, *, account_id: str = "acc1") -> Tx:
    return Tx(
        id=f"privat_h_{idx:016x}",
        account_id=account_id,
        ts=1_700_000_000 + idx,
        amount_minor=-1000 - idx,
        currency_code=980,
        op_amount_minor=None,
        op_currency_code=None,
        mcc=None,
        description=f"row{idx}",
        counterparty=None,
        balance_minor=10_000 - idx,
        raw={"i": idx},
    )


def test_open_db_brings_up_schema(tmp_path: Path) -> None:
    conn = open_db(tmp_path / "data.db")
    tables = {
        r[0]
        for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name LIKE 'privat_%'"
        )
    }
    assert tables == {
        "privat_accounts",
        "privat_import_runs",
        "privat_schema_version",
        "privat_transactions",
    }
    v = conn.execute("SELECT MAX(version) FROM privat_schema_version").fetchone()[0]
    assert v == 1


def test_insert_then_repeat_is_idempotent(tmp_path: Path) -> None:
    conn = open_db(tmp_path / "data.db")
    run = start_import_run(conn, source="xlsx", file_path="t.xlsx", file_sha256="abc")
    out1 = insert_transactions(
        conn, run_id=run, txs=[_tx(0), _tx(1), _tx(2)], account=_acc()
    )
    out2 = insert_transactions(
        conn, run_id=run, txs=[_tx(0), _tx(1), _tx(2)], account=_acc()
    )
    finish_import_run(
        conn, run, rows_inserted=out1.rows_inserted, rows_skipped=out1.rows_skipped
    )
    assert out1 == InsertOutcome(rows_inserted=3, rows_skipped=0)
    assert out2 == InsertOutcome(rows_inserted=0, rows_skipped=3)
    count = conn.execute("SELECT COUNT(*) FROM privat_transactions").fetchone()[0]
    assert count == 3


def test_insert_rolls_back_on_fk_violation(tmp_path: Path) -> None:
    """If any row in a batch references an unknown account, the entire
    transaction rolls back and zero inserts persist. Mirrors the
    monobank-mcp atomicity invariant."""
    conn = open_db(tmp_path / "data.db")
    # Seed acc1 via the normal ingest path with an empty tx batch.
    seed_run = start_import_run(
        conn, source="xlsx", file_path="seed.xlsx", file_sha256="seed"
    )
    insert_transactions(conn, run_id=seed_run, txs=[], account=_acc())
    run = start_import_run(conn, source="xlsx", file_path="t.xlsx", file_sha256="abc")
    txs = [_tx(0, account_id="acc1"), _tx(1, account_id="ghost")]
    with pytest.raises(sqlite3.IntegrityError):
        insert_transactions(conn, run_id=run, txs=txs)
    count = conn.execute("SELECT COUNT(*) FROM privat_transactions").fetchone()[0]
    assert count == 0


def test_atomic_account_and_tx_rollback_on_fk_failure(tmp_path: Path) -> None:
    """When the caller passes ``account=`` and the inserts then fail mid-
    batch, both the account upsert AND the txs must roll back together.
    This proves the fix for the "dangling account row" review finding.

    We trigger failure via an unknown FK on the second tx; the first tx
    cites a fresh account that should not survive the rollback."""
    conn = open_db(tmp_path / "data.db")
    run = start_import_run(conn, source="xlsx", file_path="t.xlsx", file_sha256="abc")
    fresh_account = AccountSpec(
        account_id="fresh_acc",
        iban=None,
        account_type=None,
        currency_code=980,
        masked_pan="4111 **** **** 9999",
    )
    txs = [_tx(0, account_id="fresh_acc"), _tx(1, account_id="ghost")]
    with pytest.raises(sqlite3.IntegrityError):
        insert_transactions(conn, run_id=run, txs=txs, account=fresh_account)
    # Both must be absent: dangling account would be a regression.
    tx_count = conn.execute("SELECT COUNT(*) FROM privat_transactions").fetchone()[0]
    acc_count = conn.execute(
        "SELECT COUNT(*) FROM privat_accounts WHERE account_id = 'fresh_acc'"
    ).fetchone()[0]
    assert tx_count == 0
    assert acc_count == 0


def test_already_imported_returns_run_id(tmp_path: Path) -> None:
    conn = open_db(tmp_path / "data.db")
    run = start_import_run(
        conn, source="xlsx", file_path="t.xlsx", file_sha256="deadbeef"
    )
    finish_import_run(conn, run, rows_inserted=0, rows_skipped=0)
    assert already_imported(conn, "deadbeef") == run
    assert already_imported(conn, "no-such-sha") is None


def test_migration_is_atomic_on_failure(tmp_path: Path) -> None:
    """Inject a faulty migration to prove the BEGIN/COMMIT envelope
    rolls back on error. Before the fix, ``executescript`` would issue
    an implicit COMMIT before the script ran and partial DDL would
    leak. After the fix, the connection rejects all of it.
    """
    import privat24_import.core.store as store

    # Empty DB; raw connection bypasses open_db so we control migrations.
    conn = sqlite3.connect(tmp_path / "data.db")
    try:
        conn.execute("PRAGMA foreign_keys = ON")
        # Patch the migrations list with a broken script. The script
        # also CREATEs privat_schema_version so we can verify the entire
        # bootstrap - including the version-tracker table - rolls back.
        original_files = store._MIGRATION_FILES
        original_loader = store._load_migration_sql
        store._MIGRATION_FILES = [(1, "_test_bad.sql")]
        store._load_migration_sql = lambda _name: (  # type: ignore[assignment]
            "CREATE TABLE privat_schema_version ("
            "  version INTEGER PRIMARY KEY, applied_at INTEGER NOT NULL);"
            "CREATE TABLE privat_test_a (id INTEGER);"
            "CREATE TABLE privat_test_b (id INTEGER);"
            "THIS IS NOT VALID SQL;"
            "INSERT INTO privat_schema_version VALUES (1, 0);"
        )
        try:
            with pytest.raises(sqlite3.OperationalError):
                ensure_privat_schema(conn)
            # None of the tables from the failed migration may exist -
            # including privat_schema_version itself, which proves the
            # bootstrap is no longer outside the transaction.
            n = conn.execute(
                "SELECT COUNT(*) FROM sqlite_master "
                "WHERE name IN ('privat_test_a', 'privat_test_b', 'privat_schema_version')"
            ).fetchone()[0]
            assert n == 0, "partial DDL leaked - atomicity broken"
        finally:
            store._MIGRATION_FILES = original_files
            store._load_migration_sql = original_loader  # type: ignore[assignment]
    finally:
        conn.close()
