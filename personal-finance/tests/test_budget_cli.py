"""End-to-end ``pf-budget`` CLI tests for PR1 (registry surface)."""

from __future__ import annotations

import contextlib
import json
import sqlite3
from pathlib import Path

import pytest

from pf_skill.budget_cli import main
from pf_skill.common import budget as bud
from pf_skill.common.store import open_db


def _run(argv: list[str], capsys: pytest.CaptureFixture[str]) -> tuple[int, dict, str]:
    rc = main(argv)
    captured = capsys.readouterr()
    payload: dict = {}
    if captured.out.strip():
        payload = json.loads(captured.out)
    err_payload: dict = {}
    if captured.err.strip():
        with contextlib.suppress(json.JSONDecodeError, IndexError):
            err_payload = json.loads(captured.err.splitlines()[-1])
    return rc, payload or err_payload, captured.err


# --- register-category -------------------------------------------------------


def test_register_category_inserts_row(empty_db: Path, capsys: pytest.CaptureFixture[str]) -> None:
    rc, payload, err = _run(
        [
            "register-category",
            "--category",
            "Покупки/Сад",
            "--note",
            "Дача",
            "--db",
            str(empty_db),
        ],
        capsys,
    )
    assert rc == 0, err
    assert payload["ok"] is True
    assert payload["already_registered"] is False
    assert payload["category"] == "Покупки/Сад"
    assert payload["declared_via"] == "cli"
    assert payload["note"] == "Дача"
    conn = sqlite3.connect(empty_db)
    try:
        row = conn.execute("SELECT category, declared_via, note FROM category_registry").fetchone()
    finally:
        conn.close()
    assert row == ("Покупки/Сад", "cli", "Дача")


def test_register_category_idempotent_does_not_rewrite_metadata(
    empty_db: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Second call returns already_registered=True and keeps the
    original declared_at / note - so audit trail is preserved."""
    _run(
        [
            "register-category",
            "--category",
            "Покупки/Сад",
            "--note",
            "first call",
            "--db",
            str(empty_db),
        ],
        capsys,
    )
    rc, payload, err = _run(
        [
            "register-category",
            "--category",
            "Покупки/Сад",
            "--note",
            "second call",
            "--db",
            str(empty_db),
        ],
        capsys,
    )
    assert rc == 0, err
    assert payload["ok"] is True
    assert payload["already_registered"] is True
    assert payload["note"] == "first call"  # original metadata kept


def test_register_category_rejects_whitespace_padded_name(
    empty_db: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    rc, _, err = _run(
        [
            "register-category",
            "--category",
            "  Покупки/Дім  ",
            "--db",
            str(empty_db),
        ],
        capsys,
    )
    assert rc == 1
    assert "leading or trailing whitespace" in err


def test_register_category_rejects_bad_hierarchy_shape(
    empty_db: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    rc, _, err = _run(
        [
            "register-category",
            "--category",
            "Покупки//Дім",
            "--db",
            str(empty_db),
        ],
        capsys,
    )
    assert rc == 1
    assert "empty hierarchy segments" in err


# --- unregister-category -----------------------------------------------------


def test_unregister_category_removes_unreferenced(
    empty_db: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    _run(
        [
            "register-category",
            "--category",
            "Покупки/Сад",
            "--db",
            str(empty_db),
        ],
        capsys,
    )
    rc, payload, err = _run(
        [
            "unregister-category",
            "--category",
            "Покупки/Сад",
            "--db",
            str(empty_db),
        ],
        capsys,
    )
    assert rc == 0, err
    assert payload["removed"] is True
    conn = sqlite3.connect(empty_db)
    try:
        n = conn.execute("SELECT COUNT(*) FROM category_registry").fetchone()[0]
    finally:
        conn.close()
    assert n == 0


def test_unregister_category_refuses_when_in_use(
    empty_db: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Register a category, then pin a tx to it via tx_category, then
    try to unregister - should fail with StillInUse."""
    _run(
        [
            "register-category",
            "--category",
            "Test/Cat",
            "--db",
            str(empty_db),
        ],
        capsys,
    )
    # Inject a fake tx_category row directly (no need for a real tx).
    conn = sqlite3.connect(empty_db)
    try:
        conn.execute(
            "INSERT INTO tx_category (tx_id, category, set_at, set_by) "
            "VALUES ('fake_tx', 'Test/Cat', 1700000000, 'manual')"
        )
        conn.commit()
    finally:
        conn.close()

    rc, _, err = _run(
        [
            "unregister-category",
            "--category",
            "Test/Cat",
            "--db",
            str(empty_db),
        ],
        capsys,
    )
    assert rc == 1
    assert "still referenced" in err
    assert "StillInUse" in err


def test_unregister_category_not_in_registry(
    empty_db: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    rc, _, err = _run(
        [
            "unregister-category",
            "--category",
            "Невідомо/Що",
            "--db",
            str(empty_db),
        ],
        capsys,
    )
    assert rc == 1
    assert "not in the registry" in err


def test_unregister_category_force_bypasses_in_use_check(
    empty_db: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    _run(
        ["register-category", "--category", "Test/Cat", "--db", str(empty_db)],
        capsys,
    )
    conn = sqlite3.connect(empty_db)
    try:
        conn.execute(
            "INSERT INTO tx_category (tx_id, category, set_at, set_by) "
            "VALUES ('fake_tx2', 'Test/Cat', 1700000000, 'manual')"
        )
        conn.commit()
    finally:
        conn.close()
    rc, payload, err = _run(
        [
            "unregister-category",
            "--category",
            "Test/Cat",
            "--force",
            "--db",
            str(empty_db),
        ],
        capsys,
    )
    assert rc == 0, err
    assert payload["removed"] is True


# --- list-categories ---------------------------------------------------------


def test_list_categories_in_use_only_by_default(
    both_banks_db: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """When --include-declared is NOT set, declared-but-unused entries
    must not appear in the output."""
    # Register a category that has no transactions.
    _run(
        [
            "register-category",
            "--category",
            "Декларовано/Безфактів",
            "--db",
            str(both_banks_db),
        ],
        capsys,
    )
    # Pin one tx to a category so something is in-use.
    conn = sqlite3.connect(both_banks_db)
    try:
        conn.execute(
            "INSERT INTO tx_category (tx_id, category, set_at, set_by) "
            "VALUES ('mono_t1', 'Реальна/Категорія', 1700000000, 'manual')"
        )
        conn.commit()
    finally:
        conn.close()

    rc, payload, err = _run(
        ["list-categories", "--db", str(both_banks_db)],
        capsys,
    )
    assert rc == 0, err
    names = {c["category"] for c in payload["categories"]}
    assert "Реальна/Категорія" in names
    assert "Декларовано/Безфактів" not in names
    for c in payload["categories"]:
        assert c["declared"] is False


def test_list_categories_include_declared_surfaces_registry(
    both_banks_db: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    _run(
        [
            "register-category",
            "--category",
            "Декларовано/Безфактів",
            "--db",
            str(both_banks_db),
        ],
        capsys,
    )
    rc, payload, err = _run(
        ["list-categories", "--include-declared", "--db", str(both_banks_db)],
        capsys,
    )
    assert rc == 0, err
    declared_entry = next(
        c for c in payload["categories"] if c["category"] == "Декларовано/Безфактів"
    )
    assert declared_entry["tx_count"] == 0
    assert declared_entry["declared"] is True


def test_list_categories_does_not_duplicate_when_both_in_use_and_declared(
    both_banks_db: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """A category that's both in tx_category AND in category_registry
    must appear once - as the in-use entry, NOT duplicated."""
    # Trigger schema bring-up via the CLI before raw INSERTs touch
    # ``tx_category`` (which lives in the pf_001 migration).
    _run(
        ["register-category", "--category", "Both/Sides", "--db", str(both_banks_db)],
        capsys,
    )
    conn = sqlite3.connect(both_banks_db)
    try:
        conn.execute(
            "INSERT INTO tx_category (tx_id, category, set_at, set_by) "
            "VALUES ('mono_t1', 'Both/Sides', 1700000000, 'manual')"
        )
        conn.commit()
    finally:
        conn.close()
    rc, payload, err = _run(
        ["list-categories", "--include-declared", "--db", str(both_banks_db)],
        capsys,
    )
    assert rc == 0, err
    both_entries = [c for c in payload["categories"] if c["category"] == "Both/Sides"]
    assert len(both_entries) == 1
    assert both_entries[0]["tx_count"] == 1
    assert both_entries[0]["declared"] is False


def test_list_categories_surfaces_budget_only_category(
    both_banks_db: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """A category that exists only as a budget line must be listed.

    This is the ``Транспорт/Страхування`` trap: the plan carries the
    line, nothing has landed on it yet this period, so a taxonomy
    listing that reads transactions alone hides it - and the next
    categorisation invents ``Транспорт/Страховка`` for the same thing,
    leaving an unfired planned line beside an unplanned charge.
    """
    conn = open_db(both_banks_db)
    try:
        conn.execute(
            "INSERT INTO tx_category (tx_id, category, set_at, set_by) "
            "VALUES ('mono_t1', 'Реальна/Категорія', 1700000000, 'manual')"
        )
        bud.materialise_budget(
            conn,
            period="2023-11",
            rows=[
                bud.PlanRow("2023-11", "Транспорт/Страхування", 980, "baseline", -800000),
                bud.PlanRow("2023-11", "Реальна/Категорія", 980, "baseline", -50000),
            ],
            source="seed",
        )
    finally:
        conn.close()

    rc, payload, err = _run(["list-categories", "--db", str(both_banks_db)], capsys)
    assert rc == 0, err
    by = {c["category"]: c for c in payload["categories"]}

    planned = by["Транспорт/Страхування"]
    assert planned["tx_count"] == 0
    assert planned["in_budget"] is True
    # Not a registry declaration - it is a real planned line.
    assert planned["declared"] is False

    # A category that is both in use and budgeted appears once, flagged.
    in_use = by["Реальна/Категорія"]
    assert in_use["tx_count"] == 1
    assert in_use["in_budget"] is True
    assert len([c for c in payload["categories"] if c["category"] == "Реальна/Категорія"]) == 1


def test_list_categories_marks_unbudgeted_categories(
    both_banks_db: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """With no budget at all, every row is flagged in_budget False."""
    conn = open_db(both_banks_db)
    try:
        conn.execute(
            "INSERT INTO tx_category (tx_id, category, set_at, set_by) "
            "VALUES ('mono_t1', 'Реальна/Категорія', 1700000000, 'manual')"
        )
    finally:
        conn.close()
    rc, payload, err = _run(["list-categories", "--db", str(both_banks_db)], capsys)
    assert rc == 0, err
    assert payload["categories"]
    for c in payload["categories"]:
        assert c["in_budget"] is False
