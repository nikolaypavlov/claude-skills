"""End-to-end integration tests: import a fixture, verify DB state, then
re-import the same file to confirm idempotency."""

from __future__ import annotations

import sqlite3
from pathlib import Path

from privat24_import.__main__ import import_one


def _row_count(db: Path) -> int:
    conn = sqlite3.connect(db)
    try:
        return conn.execute("SELECT COUNT(*) FROM privat_transactions").fetchone()[0]
    finally:
        conn.close()


def _account_count(db: Path) -> int:
    conn = sqlite3.connect(db)
    try:
        return conn.execute("SELECT COUNT(*) FROM privat_accounts").fetchone()[0]
    finally:
        conn.close()


def test_import_fixture_writes_30_rows(tmp_path: Path, sample_xlsx: Path) -> None:
    data_dir = tmp_path / "data"
    result = import_one(sample_xlsx, data_dir=data_dir, do_archive=False)
    assert result["status"] == "imported", result
    assert result["rows_inserted"] == 30
    assert result["rows_skipped"] == 0
    assert _row_count(data_dir / "data.db") == 30
    assert _account_count(data_dir / "data.db") == 1


def test_reimport_same_file_short_circuits_on_sha(
    tmp_path: Path, sample_xlsx: Path
) -> None:
    data_dir = tmp_path / "data"
    first = import_one(sample_xlsx, data_dir=data_dir, do_archive=False)
    second = import_one(sample_xlsx, data_dir=data_dir, do_archive=False)
    assert first["status"] == "imported"
    assert second["status"] == "skipped"
    assert second["import_run_id"] == first["import_run_id"]
    assert _row_count(data_dir / "data.db") == 30
    # The short-circuit must NOT write a new import_run row. Without
    # this assertion a regression that calls start_import_run before
    # the short-circuit guard would still pass the row count check
    # (already_imported returns the lowest id by ORDER BY).
    conn = sqlite3.connect(data_dir / "data.db")
    try:
        runs = conn.execute("SELECT COUNT(*) FROM privat_import_runs").fetchone()[0]
        assert runs == 1, f"expected exactly 1 import_run row, got {runs}"
    finally:
        conn.close()


def test_archive_moves_file(tmp_path: Path, sample_xlsx: Path) -> None:
    data_dir = tmp_path / "data"
    # sample_xlsx already lives under tmp_path (conftest copies it), so
    # archiving will move it under data_dir/archive/.
    result = import_one(sample_xlsx, data_dir=data_dir, do_archive=True)
    assert result["status"] == "imported"
    assert result["archived_to"] is not None
    archived = Path(result["archived_to"])
    assert archived.exists()
    assert archived.parent.parent.name == "archive"
    # Original path should be gone.
    assert not sample_xlsx.exists()


def test_import_error_path_records_run_with_error_column(tmp_path: Path) -> None:
    """When the parser raises after ``start_import_run`` has committed,
    the error must land in ``privat_import_runs.error`` AND the result
    dict must surface it. We trigger this by feeding an XLSX with the
    correct header sniff but a body that fails downstream parsing -
    here, two distinct cards in one file (multi-card rejection)."""
    from openpyxl import Workbook
    from privat24_import.parsers.detect import WEB_XLSX_HEADERS

    out = tmp_path / "bad.xlsx"
    wb = Workbook()
    ws = wb.active
    assert ws is not None
    ws.title = "Виписки"
    ws.append(["Історія операцій за період"] + [""] * 9)
    ws.append(list(WEB_XLSX_HEADERS))
    ws.append(
        (
            "20.05.2026 09:00:00",
            "Магазини",
            "5168 **** **** 1111",
            "card A",
            -100.0,
            "UAH",
            100.0,
            "UAH",
            1000.0,
            "UAH",
        )
    )
    ws.append(
        (
            "20.05.2026 09:30:00",
            "Магазини",
            "5168 **** **** 2222",
            "card B",
            -50.0,
            "UAH",
            50.0,
            "UAH",
            950.0,
            "UAH",
        )
    )
    wb.save(out)

    data_dir = tmp_path / "data"
    result = import_one(out, data_dir=data_dir, do_archive=False)
    assert result["status"] == "error", result
    assert result["import_run_id"] is not None
    assert result["error"] and "one card" in result["error"]

    conn = sqlite3.connect(data_dir / "data.db")
    try:
        row = conn.execute(
            "SELECT error, finished_at FROM privat_import_runs WHERE id = ?",
            (result["import_run_id"],),
        ).fetchone()
        assert row is not None
        error_col, finished_at = row
        assert error_col and "one card" in error_col
        assert finished_at is not None
        # And no rows leaked through despite the run row being recorded.
        tx_count = conn.execute("SELECT COUNT(*) FROM privat_transactions").fetchone()[
            0
        ]
        assert tx_count == 0
    finally:
        conn.close()


def test_open_db_failure_returns_clean_error(tmp_path: Path, sample_xlsx: Path) -> None:
    """If ``open_db`` raises - e.g. because the data dir is not writable -
    the failure must surface as ``status: error`` JSON instead of a
    traceback escaping the JSON-on-stdout contract."""
    # Point the data dir at an existing FILE so creating data.db's
    # parent directory will fail with NotADirectoryError (subclass of
    # OSError).
    bogus = tmp_path / "not_a_dir"
    bogus.write_text("blocker")
    result = import_one(sample_xlsx, data_dir=bogus, do_archive=False)
    assert result["status"] == "error", result
    assert result["error"] and "cannot open database" in result["error"]


def test_unsupported_file_does_not_crash(tmp_path: Path) -> None:
    txt = tmp_path / "thing.csv"
    txt.write_text("not an xlsx\n")
    data_dir = tmp_path / "data"
    result = import_one(txt, data_dir=data_dir, do_archive=False)
    assert result["status"] == "unsupported"
    assert "extension" in result["error"]
    # No partial state: import_run row not created for unsupported files.
    db = data_dir / "data.db"
    if db.exists():
        conn = sqlite3.connect(db)
        try:
            assert (
                conn.execute("SELECT COUNT(*) FROM privat_import_runs").fetchone()[0]
                == 0
            )
        finally:
            conn.close()
