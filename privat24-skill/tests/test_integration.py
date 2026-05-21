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
