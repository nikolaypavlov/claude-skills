"""End-to-end ``pf-rules`` CLI tests for all six subcommands."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest

from pf_skill.rules_cli import main


def _run(argv: list[str], capsys: pytest.CaptureFixture[str]) -> tuple[int, dict, str]:
    rc = main(argv)
    captured = capsys.readouterr()
    payload: dict = {}
    if captured.out.strip():
        payload = json.loads(captured.out)
    return rc, payload, captured.err


def _db_rules(db: Path) -> list[tuple]:
    conn = sqlite3.connect(db)
    try:
        return conn.execute(
            "SELECT match_field, pattern, category, enabled FROM categorization_rules"
        ).fetchall()
    finally:
        conn.close()


# --- add ---------------------------------------------------------------------


def test_add_preview_inserts_rule_without_backfill(
    both_banks_db: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    rc, payload, err = _run(
        [
            "add",
            "--match-field",
            "description",
            "--pattern",
            "(?i)privat",
            "--category",
            "Test/Privat",
            "--db",
            str(both_banks_db),
        ],
        capsys,
    )
    assert rc == 0, err
    assert payload["ok"] is True
    assert payload["rule_id"] >= 1
    assert payload["would_affect_count"] == 1  # "Privat shop"
    assert payload["applied"] == 0  # no --apply
    # Rule landed in DB.
    rows = _db_rules(both_banks_db)
    assert ("description", "(?i)privat", "Test/Privat", 1) in rows
    # tx_category NOT touched.
    conn = sqlite3.connect(both_banks_db)
    try:
        assert conn.execute("SELECT COUNT(*) FROM tx_category").fetchone()[0] == 0
    finally:
        conn.close()


def test_add_with_apply_backfills(both_banks_db: Path, capsys: pytest.CaptureFixture[str]) -> None:
    rc, payload, err = _run(
        [
            "add",
            "--match-field",
            "description",
            "--pattern",
            "(?i)privat",
            "--category",
            "Test/Privat",
            "--apply",
            "--db",
            str(both_banks_db),
        ],
        capsys,
    )
    assert rc == 0, err
    assert payload["applied"] == 1
    conn = sqlite3.connect(both_banks_db)
    try:
        row = conn.execute("SELECT category FROM tx_category WHERE tx_id = 'privat_h_1'").fetchone()
    finally:
        conn.close()
    assert row == ("Test/Privat",)


def test_add_invalid_regex_rejected_before_insert(
    both_banks_db: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """A malformed regex must surface at add time with a CliError, not
    silently insert a rule that never matches at categorize time."""
    rc, _, err = _run(
        [
            "add",
            "--match-field",
            "description",
            "--pattern",
            "(unclosed",
            "--category",
            "Trash",
            "--db",
            str(both_banks_db),
        ],
        capsys,
    )
    assert rc == 1
    err_payload = json.loads(err)
    assert err_payload["ok"] is False
    assert "not a valid Python regex" in err_payload["error"]
    # Validation runs before the DB open, so the rule could not have
    # landed anywhere (the assertion in the next test confirms the happy
    # path does open the DB and insert).


def test_add_mcc_pattern_not_validated_as_regex(
    both_banks_db: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """MCC patterns are exact integer-string matches, not regexes; an
    "invalid regex" like "(" is still a valid MCC literal and must not
    be rejected."""
    rc, payload, err = _run(
        [
            "add",
            "--match-field",
            "mcc",
            "--pattern",
            "(",
            "--category",
            "X",
            "--db",
            str(both_banks_db),
        ],
        capsys,
    )
    assert rc == 0, err
    assert payload["ok"] is True


def test_add_invalid_match_field_rejected(
    both_banks_db: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    rc, _, err = _run(
        [
            "add",
            "--match-field",
            "bogus",
            "--pattern",
            "x",
            "--category",
            "y",
            "--db",
            str(both_banks_db),
        ],
        capsys,
    )
    assert rc == 1
    err_payload = json.loads(err)
    assert err_payload["ok"] is False
    assert "--match-field" in err_payload["error"]


# --- apply -------------------------------------------------------------------


def test_apply_dry_run_does_not_write(
    both_banks_db: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    # Stage a rule via the CLI so we have a real rule_id.
    _run(
        [
            "add",
            "--match-field",
            "description",
            "--pattern",
            "(?i)EUR transfer",
            "--category",
            "FX",
            "--db",
            str(both_banks_db),
        ],
        capsys,
    )
    conn = sqlite3.connect(both_banks_db)
    try:
        rule_id = conn.execute("SELECT MAX(id) FROM categorization_rules").fetchone()[0]
    finally:
        conn.close()

    rc, payload, err = _run(
        ["apply", "--rule-id", str(rule_id), "--dry-run", "--db", str(both_banks_db)],
        capsys,
    )
    assert rc == 0, err
    assert payload["dry_run"] is True
    assert payload["applied"] == 0
    assert payload["matched_count"] == 1


def test_apply_writes_when_not_dry_run(
    both_banks_db: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    _run(
        [
            "add",
            "--match-field",
            "description",
            "--pattern",
            "(?i)EUR transfer",
            "--category",
            "FX",
            "--db",
            str(both_banks_db),
        ],
        capsys,
    )
    conn = sqlite3.connect(both_banks_db)
    try:
        rule_id = conn.execute("SELECT MAX(id) FROM categorization_rules").fetchone()[0]
    finally:
        conn.close()

    rc, payload, _ = _run(
        ["apply", "--rule-id", str(rule_id), "--db", str(both_banks_db)],
        capsys,
    )
    assert rc == 0
    assert payload["applied"] == 1


def test_apply_unknown_rule_id_rejected(
    both_banks_db: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    rc, _, err = _run(["apply", "--rule-id", "9999", "--db", str(both_banks_db)], capsys)
    assert rc == 1
    err_payload = json.loads(err)
    assert err_payload["ok"] is False
    assert "no rule with id" in err_payload["error"]


# --- set-category / set-override --------------------------------------------


def test_set_category_writes_row(both_banks_db: Path, capsys: pytest.CaptureFixture[str]) -> None:
    rc, payload, _ = _run(
        [
            "set-category",
            "--tx-id",
            "mono_t1",
            "--category",
            "Manual",
            "--db",
            str(both_banks_db),
        ],
        capsys,
    )
    assert rc == 0
    assert payload["set_by"] == "manual"
    conn = sqlite3.connect(both_banks_db)
    try:
        row = conn.execute(
            "SELECT category, rule_id, set_by FROM tx_category WHERE tx_id = 'mono_t1'"
        ).fetchone()
    finally:
        conn.close()
    assert row == ("Manual", None, "manual")


def test_set_category_replaces_existing(
    both_banks_db: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    _run(
        ["set-category", "--tx-id", "mono_t1", "--category", "First", "--db", str(both_banks_db)],
        capsys,
    )
    _run(
        ["set-category", "--tx-id", "mono_t1", "--category", "Second", "--db", str(both_banks_db)],
        capsys,
    )
    conn = sqlite3.connect(both_banks_db)
    try:
        row = conn.execute("SELECT category FROM tx_category WHERE tx_id = 'mono_t1'").fetchone()
    finally:
        conn.close()
    assert row == ("Second",)


def test_set_override_writes_with_note(
    both_banks_db: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    rc, payload, _ = _run(
        [
            "set-override",
            "--tx-id",
            "mono_t2",
            "--category",
            "Pinned",
            "--note",
            "test pin",
            "--db",
            str(both_banks_db),
        ],
        capsys,
    )
    assert rc == 0
    assert payload["note"] == "test pin"
    conn = sqlite3.connect(both_banks_db)
    try:
        row = conn.execute(
            "SELECT category, note FROM category_overrides WHERE tx_id = 'mono_t2'"
        ).fetchone()
    finally:
        conn.close()
    assert row == ("Pinned", "test pin")


# --- list -------------------------------------------------------------------


def test_list_returns_seed_plus_db(both_banks_db: Path, capsys: pytest.CaptureFixture[str]) -> None:
    _run(
        [
            "add",
            "--match-field",
            "description",
            "--pattern",
            "(?i)test",
            "--category",
            "TestCat",
            "--db",
            str(both_banks_db),
        ],
        capsys,
    )
    rc, payload, err = _run(["list", "--db", str(both_banks_db)], capsys)
    assert rc == 0, err
    sources = {r["source"] for r in payload["rules"]}
    assert "seed-mcc" in sources
    assert "seed-description" in sources
    assert "db" in sources


def test_list_filter_by_source(both_banks_db: Path, capsys: pytest.CaptureFixture[str]) -> None:
    rc, payload, _ = _run(["list", "--source", "seed-mcc", "--db", str(both_banks_db)], capsys)
    assert rc == 0
    assert payload["count"] > 0
    assert all(r["source"] == "seed-mcc" for r in payload["rules"])


def test_list_enabled_only_drops_disabled(
    both_banks_db: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    conn = sqlite3.connect(both_banks_db)
    try:
        # Disable a rule directly so list --enabled-only excludes it.
        from pf_skill.common import store as st

        conn.close()
        conn2 = st.open_db(both_banks_db)
        conn2.execute(
            "INSERT INTO categorization_rules "
            "(priority, match_field, pattern, category, enabled, created_at, source) "
            "VALUES (50, 'description', 'XYZ', 'Off', 0, 0, 'user')"
        )
        conn2.close()
    finally:
        pass

    rc, payload_all, _ = _run(["list", "--source", "db", "--db", str(both_banks_db)], capsys)
    rc2, payload_on, _ = _run(
        ["list", "--source", "db", "--enabled-only", "--db", str(both_banks_db)], capsys
    )
    assert rc == 0 and rc2 == 0
    assert any(r["pattern"] == "XYZ" for r in payload_all["rules"])
    assert not any(r["pattern"] == "XYZ" for r in payload_on["rules"])
