"""Store smoke tests: schema bring-up, FK enforcement, idempotent inserts."""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest
from privat24_import.core.store import (
    InsertOutcome,
    Tx,
    already_imported,
    finish_import_run,
    insert_transactions,
    open_db,
    start_import_run,
    upsert_account,
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
    upsert_account(
        conn,
        account_id="acc1",
        iban=None,
        account_type=None,
        currency_code=980,
        masked_pan="4111 **** **** 0000",
    )
    run = start_import_run(conn, source="xlsx", file_path="t.xlsx", file_sha256="abc")
    out1 = insert_transactions(conn, run_id=run, txs=[_tx(0), _tx(1), _tx(2)])
    out2 = insert_transactions(conn, run_id=run, txs=[_tx(0), _tx(1), _tx(2)])
    finish_import_run(
        conn, run, rows_inserted=out1.rows_inserted, rows_skipped=out1.rows_skipped
    )
    assert out1 == InsertOutcome(rows_inserted=3, rows_skipped=0)
    assert out2 == InsertOutcome(rows_inserted=0, rows_skipped=3)
    count = conn.execute("SELECT COUNT(*) FROM privat_transactions").fetchone()[0]
    assert count == 3


def test_insert_rolls_back_on_fk_violation(tmp_path: Path) -> None:
    """If any row in a batch references an unknown account, the entire
    transaction rolls back and the cursor (here import_run) sees zero
    inserts. Mirrors the monobank-mcp atomicity invariant."""
    conn = open_db(tmp_path / "data.db")
    upsert_account(
        conn,
        account_id="acc1",
        iban=None,
        account_type=None,
        currency_code=980,
        masked_pan="4111 **** **** 0000",
    )
    run = start_import_run(conn, source="xlsx", file_path="t.xlsx", file_sha256="abc")
    txs = [_tx(0, account_id="acc1"), _tx(1, account_id="ghost")]
    with pytest.raises(sqlite3.IntegrityError):
        insert_transactions(conn, run_id=run, txs=txs)
    count = conn.execute("SELECT COUNT(*) FROM privat_transactions").fetchone()[0]
    assert count == 0


def test_already_imported_returns_run_id(tmp_path: Path) -> None:
    conn = open_db(tmp_path / "data.db")
    run = start_import_run(
        conn, source="xlsx", file_path="t.xlsx", file_sha256="deadbeef"
    )
    finish_import_run(conn, run, rows_inserted=0, rows_skipped=0)
    assert already_imported(conn, "deadbeef") == run
    assert already_imported(conn, "no-such-sha") is None
