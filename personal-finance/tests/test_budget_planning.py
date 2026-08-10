"""Conversation-driven planning: draft lifecycle + line-level edits + undo.

Covers:
- start_draft / commit_draft / cancel_draft
- add_line / update_line / remove_line (both line_id and composite key)
- undo_last in all three operation directions (add/update/remove)
- Replace-active-on-commit semantics
- Multi-currency draft (UAH + USD lines in one planning session)
- CLI end-to-end via budget_cli.main
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest

from pf_skill.budget_cli import main
from pf_skill.common import budget as bud
from pf_skill.common.store import open_db


def _run(argv: list[str], capsys: pytest.CaptureFixture[str]) -> tuple[int, dict, dict]:
    rc = main(argv)
    captured = capsys.readouterr()
    out: dict = json.loads(captured.out) if captured.out.strip() else {}
    err: dict = {}
    if captured.err.strip():
        try:
            err = json.loads(captured.err.splitlines()[-1])
        except json.JSONDecodeError:
            err = {"raw": captured.err}
    return rc, out, err


def _seed_active(db: Path, period: str, *rows: tuple) -> None:
    """rows: (category, currency_code, kind, amount_minor[, note])."""
    conn = open_db(db)
    plan_rows = [
        bud.PlanRow(
            period,
            r[0],
            r[1],
            r[2],
            r[3],
            r[4] if len(r) > 4 else None,
        )
        for r in rows
    ]
    bud.materialise_budget(conn, period=period, rows=plan_rows, source="seed")
    conn.close()


# --- start_draft ------------------------------------------------------------


def test_start_draft_copies_baseline_from_prior_active(empty_db: Path) -> None:
    _seed_active(
        empty_db,
        "2026-06",
        ("Їжа/Ресторани", 980, "baseline", -900000),
        ("Подорожі/Готелі", 980, "one_time", -1260000),  # excluded
        ("Інвестиції/Облігації", 840, "baseline", -170000),
    )
    conn = open_db(empty_db)
    result = bud.start_draft(conn, period="2026-07")
    conn.close()

    assert result["existing_draft"] is False
    assert result["copied_from"] == "2026-06"
    assert result["in_place"] is False
    # 2 currencies → 2 draft budgets
    assert len(result["drafts"]) == 2
    by_cur = {d["currency_code"]: d for d in result["drafts"]}
    assert by_cur[980]["lines_copied"] == 1  # Only baseline; one_time excluded
    assert by_cur[840]["lines_copied"] == 1


def test_start_draft_returns_existing_without_recreating(empty_db: Path) -> None:
    _seed_active(empty_db, "2026-06", ("X", 980, "baseline", -1000))
    conn = open_db(empty_db)
    first = bud.start_draft(conn, period="2026-07")
    second = bud.start_draft(conn, period="2026-07")
    conn.close()
    assert first["existing_draft"] is False
    assert second["existing_draft"] is True
    assert second["drafts"][0]["budget_id"] == first["drafts"][0]["budget_id"]


def test_start_draft_blank_when_copy_from_empty(empty_db: Path) -> None:
    _seed_active(empty_db, "2026-06", ("X", 980, "baseline", -1000))
    conn = open_db(empty_db)
    result = bud.start_draft(conn, period="2026-07", copy_from="")
    conn.close()
    assert result["copied_from"] is None
    assert result["drafts"] == []


def test_start_draft_with_explicit_copy_from(empty_db: Path) -> None:
    _seed_active(empty_db, "2026-04", ("Old", 980, "baseline", -100))
    _seed_active(empty_db, "2026-06", ("Recent", 980, "baseline", -200))
    conn = open_db(empty_db)
    # Skip the more recent budget on purpose
    result = bud.start_draft(conn, period="2026-07", copy_from="2026-04")
    conn.close()
    assert result["copied_from"] == "2026-04"
    assert result["in_place"] is False


def test_start_draft_defaults_to_own_active_period(empty_db: Path) -> None:
    """Editing a month that is already active must copy THAT month, not the
    previous one - otherwise the draft silently re-derives from stale
    numbers and commit overwrites the live budget with them."""
    _seed_active(empty_db, "2026-06", ("Stale", 980, "baseline", -100))
    _seed_active(
        empty_db,
        "2026-07",
        ("Їжа/Ресторани", 980, "baseline", -900000),
        ("Подорожі/Готелі", 980, "one_time", -1260000),
    )
    conn = open_db(empty_db)
    result = bud.start_draft(conn, period="2026-07")
    categories = {
        r[0]
        for r in conn.execute(
            "SELECT category FROM budget_line bl JOIN budget b ON b.id = bl.budget_id "
            "WHERE b.period = '2026-07' AND b.status = 'draft'"
        )
    }
    conn.close()

    assert result["copied_from"] == "2026-07"
    assert result["in_place"] is True
    # Both kinds ride along; "Stale" from June must not appear.
    assert result["drafts"][0]["lines_copied"] == 2
    assert categories == {"Їжа/Ресторани", "Подорожі/Готелі"}


def test_start_draft_in_place_keeps_one_time_through_commit(empty_db: Path) -> None:
    """Full round-trip of the in-place edit: commit REPLACES the active
    budget, so a one_time line dropped at draft time is gone for good."""
    _seed_active(
        empty_db,
        "2026-07",
        ("Їжа/Ресторани", 980, "baseline", -900000),
        ("Подорожі/Готелі", 980, "one_time", -1260000, "Відпустка"),
    )
    conn = open_db(empty_db)
    bud.start_draft(conn, period="2026-07")
    bud.update_line(
        conn,
        period="2026-07",
        category="Їжа/Ресторани",
        currency_code=980,
        kind="baseline",
        amount_minor=-800000,
    )
    bud.commit_draft(conn, period="2026-07")
    rows = dict(
        conn.execute(
            "SELECT category, amount_minor FROM budget_line bl "
            "JOIN budget b ON b.id = bl.budget_id "
            "WHERE b.period = '2026-07' AND b.status = 'active'"
        ).fetchall()
    )
    note = conn.execute(
        "SELECT note FROM budget_line bl JOIN budget b ON b.id = bl.budget_id "
        "WHERE b.period = '2026-07' AND b.status = 'active' AND bl.kind = 'one_time'"
    ).fetchone()[0]
    conn.close()

    assert rows == {"Їжа/Ресторани": -800000, "Подорожі/Готелі": -1260000}
    assert note == "Відпустка"


def test_start_draft_explicit_copy_from_same_period_is_in_place(empty_db: Path) -> None:
    _seed_active(
        empty_db,
        "2026-07",
        ("A", 980, "baseline", -100),
        ("B", 980, "one_time", -200),
    )
    conn = open_db(empty_db)
    result = bud.start_draft(conn, period="2026-07", copy_from="2026-07")
    conn.close()
    assert result["in_place"] is True
    assert result["drafts"][0]["lines_copied"] == 2


# --- add_line / update_line / remove_line + undo ----------------------------


def test_add_line_creates_draft_for_new_currency(empty_db: Path) -> None:
    """First USD line on a UAH-only draft should create the USD draft
    budget on demand."""
    _seed_active(empty_db, "2026-06", ("UAH-thing", 980, "baseline", -1000))
    conn = open_db(empty_db)
    bud.start_draft(conn, period="2026-07")
    result = bud.add_line(
        conn,
        period="2026-07",
        category="Інвестиції/Облігації",
        currency_code=840,
        kind="baseline",
        amount_minor=-170000,
    )
    conn.close()
    assert result["op"] == "add"
    assert result["line"]["currency_code"] == 840
    conn = sqlite3.connect(empty_db)
    try:
        usd_drafts = conn.execute(
            "SELECT COUNT(*) FROM budget "
            "WHERE period = '2026-07' AND currency_code = 840 AND status = 'draft'"
        ).fetchone()[0]
    finally:
        conn.close()
    assert usd_drafts == 1


def test_update_line_by_composite_key(empty_db: Path) -> None:
    _seed_active(empty_db, "2026-06", ("Їжа/Ресторани", 980, "baseline", -900000))
    conn = open_db(empty_db)
    bud.start_draft(conn, period="2026-07")
    res = bud.update_line(
        conn,
        period="2026-07",
        category="Їжа/Ресторани",
        currency_code=980,
        kind="baseline",
        amount_minor=-1500000,  # vacation bump
    )
    conn.close()
    assert res["op"] == "update"
    assert res["before"]["amount_minor"] == -900000
    assert res["after"]["amount_minor"] == -1500000


def test_update_line_ambiguous_composite_requires_line_id(empty_db: Path) -> None:
    conn = open_db(empty_db)
    bud.start_draft(conn, period="2026-07", copy_from="")
    # Two one_time lines with the same category - vacation hotels
    bud.add_line(
        conn,
        period="2026-07",
        category="Подорожі/Готелі",
        currency_code=980,
        kind="one_time",
        amount_minor=-13000,
        note="IF",
    )
    bud.add_line(
        conn,
        period="2026-07",
        category="Подорожі/Готелі",
        currency_code=980,
        kind="one_time",
        amount_minor=-12600,
        note="Lviv",
    )
    with pytest.raises(bud.BudgetParseError, match="match composite key"):
        bud.update_line(
            conn,
            period="2026-07",
            category="Подорожі/Готелі",
            currency_code=980,
            kind="one_time",
            amount_minor=-99999,
        )
    conn.close()


def test_undo_reverses_add(empty_db: Path) -> None:
    conn = open_db(empty_db)
    bud.start_draft(conn, period="2026-07", copy_from="")
    bud.add_line(
        conn,
        period="2026-07",
        category="Х",
        currency_code=980,
        kind="baseline",
        amount_minor=-100,
    )
    result = bud.undo_last(conn, period="2026-07")
    n_lines = conn.execute("SELECT COUNT(*) FROM budget_line").fetchone()[0]
    conn.close()
    assert result["undone"]["op"] == "add"
    assert result["undone"]["reverted_as"] == "remove"
    assert n_lines == 0


def test_undo_reverses_update(empty_db: Path) -> None:
    _seed_active(empty_db, "2026-06", ("X", 980, "baseline", -100))
    conn = open_db(empty_db)
    bud.start_draft(conn, period="2026-07")
    bud.update_line(
        conn,
        period="2026-07",
        category="X",
        currency_code=980,
        kind="baseline",
        amount_minor=-9999,
    )
    bud.undo_last(conn, period="2026-07")
    amt = conn.execute(
        "SELECT amount_minor FROM budget_line bl "
        "JOIN budget b ON b.id = bl.budget_id "
        "WHERE b.period = '2026-07' AND b.status = 'draft'"
    ).fetchone()[0]
    conn.close()
    assert amt == -100


def test_undo_reverses_remove(empty_db: Path) -> None:
    _seed_active(empty_db, "2026-06", ("X", 980, "baseline", -100))
    conn = open_db(empty_db)
    bud.start_draft(conn, period="2026-07")
    bud.remove_line(conn, period="2026-07", category="X", currency_code=980, kind="baseline")
    bud.undo_last(conn, period="2026-07")
    n = conn.execute(
        "SELECT COUNT(*) FROM budget_line bl "
        "JOIN budget b ON b.id = bl.budget_id "
        "WHERE b.period = '2026-07' AND b.status = 'draft'"
    ).fetchone()[0]
    conn.close()
    assert n == 1


def test_undo_when_log_empty(empty_db: Path) -> None:
    conn = open_db(empty_db)
    bud.start_draft(conn, period="2026-07", copy_from="")
    result = bud.undo_last(conn, period="2026-07")
    conn.close()
    assert result["undone"] is None


# --- commit / cancel --------------------------------------------------------


def test_commit_draft_promotes_to_active(empty_db: Path) -> None:
    conn = open_db(empty_db)
    bud.start_draft(conn, period="2026-07", copy_from="")
    bud.add_line(
        conn,
        period="2026-07",
        category="X",
        currency_code=980,
        kind="baseline",
        amount_minor=-100,
    )
    result = bud.commit_draft(conn, period="2026-07")
    assert result["committed"][0]["replaced_active_id"] is None
    status = conn.execute("SELECT status FROM budget WHERE period = '2026-07'").fetchone()[0]
    log = conn.execute("SELECT COUNT(*) FROM budget_draft_edit").fetchone()[0]
    conn.close()
    assert status == "active"
    assert log == 0  # edit log cleared on commit


def test_commit_replaces_existing_active(empty_db: Path) -> None:
    _seed_active(empty_db, "2026-07", ("Old", 980, "baseline", -999))
    conn = open_db(empty_db)
    bud.start_draft(conn, period="2026-07", copy_from="")
    bud.add_line(
        conn,
        period="2026-07",
        category="New",
        currency_code=980,
        kind="baseline",
        amount_minor=-100,
    )
    result = bud.commit_draft(conn, period="2026-07")
    assert result["committed"][0]["replaced_active_id"] is not None
    # Old budget gone, new one is active
    actives = conn.execute(
        "SELECT id FROM budget WHERE period = '2026-07' AND status = 'active'"
    ).fetchall()
    cats = conn.execute(
        "SELECT category FROM budget_line bl "
        "JOIN budget b ON b.id = bl.budget_id WHERE b.period = '2026-07'"
    ).fetchall()
    conn.close()
    assert len(actives) == 1
    assert cats == [("New",)]  # Old gone


def test_cancel_draft_removes_it(empty_db: Path) -> None:
    conn = open_db(empty_db)
    bud.start_draft(conn, period="2026-07", copy_from="")
    bud.add_line(
        conn,
        period="2026-07",
        category="X",
        currency_code=980,
        kind="baseline",
        amount_minor=-100,
    )
    bud.cancel_draft(conn, period="2026-07")
    n = conn.execute("SELECT COUNT(*) FROM budget").fetchone()[0]
    conn.close()
    assert n == 0


def test_cancel_preserves_category_registry(empty_db: Path) -> None:
    """A new category declared during planning stays in registry even
    when the draft is cancelled - declarations stand on their own."""
    conn = open_db(empty_db)
    bud.start_draft(conn, period="2026-07", copy_from="")
    conn.execute(
        "INSERT INTO category_registry (category, declared_at, declared_via) "
        "VALUES ('Покупки/Сад', 0, 'budget-import')"
    )
    bud.add_line(
        conn,
        period="2026-07",
        category="Покупки/Сад",
        currency_code=980,
        kind="one_time",
        amount_minor=-3000,
    )
    bud.cancel_draft(conn, period="2026-07")
    registered = conn.execute(
        "SELECT COUNT(*) FROM category_registry WHERE category = 'Покупки/Сад'"
    ).fetchone()[0]
    conn.close()
    assert registered == 1


# --- multi-currency in one session ------------------------------------------


def test_multicurrency_planning_session(empty_db: Path) -> None:
    """Reflects 'додай $300 на ремонт авто' on top of a UAH draft."""
    _seed_active(empty_db, "2026-06", ("UAH-thing", 980, "baseline", -1000))
    conn = open_db(empty_db)
    bud.start_draft(conn, period="2026-07")
    # User adds a USD one-time
    bud.add_line(
        conn,
        period="2026-07",
        category="Транспорт/Ремонт",
        currency_code=840,
        kind="one_time",
        amount_minor=-30000,
        note="ремонт авто",
    )
    bud.commit_draft(conn, period="2026-07")
    cur_codes = sorted(
        r[0]
        for r in conn.execute(
            "SELECT currency_code FROM budget WHERE period = '2026-07' AND status = 'active'"
        )
    )
    conn.close()
    assert cur_codes == [840, 980]


# --- CLI integration --------------------------------------------------------


def test_cli_plan_full_flow(empty_db: Path, capsys: pytest.CaptureFixture[str]) -> None:
    """End-to-end: start (copy from active June) → update → commit."""
    _seed_active(empty_db, "2026-06", ("Їжа/Ресторани", 980, "baseline", -900000))

    rc, out, err = _run(["plan", "start", "--period", "2026-07", "--db", str(empty_db)], capsys)
    assert rc == 0, err
    assert out["copied_from"] == "2026-06"

    rc, out, err = _run(
        [
            "plan",
            "update",
            "--period",
            "2026-07",
            "--category",
            "Їжа/Ресторани",
            "--currency",
            "UAH",
            "--kind",
            "baseline",
            "--amount",
            "-15000",
            "--db",
            str(empty_db),
        ],
        capsys,
    )
    assert rc == 0, err
    assert out["before"]["amount_minor"] == -900000
    assert out["after"]["amount_minor"] == -1500000

    rc, out, err = _run(["plan", "show", "--period", "2026-07", "--db", str(empty_db)], capsys)
    assert rc == 0
    assert out["viewing"] == "draft"

    rc, out, err = _run(["plan", "commit", "--period", "2026-07", "--db", str(empty_db)], capsys)
    assert rc == 0, err
    assert out["committed"][0]["line_count"] == 1


def test_cli_plan_undo_via_chat_like_sequence(
    empty_db: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Replicates 'add then undo' from a chat session."""
    _seed_active(empty_db, "2026-06", ("Освіта/Школа", 980, "baseline", -1560000))
    _run(["plan", "start", "--period", "2026-07", "--db", str(empty_db)], capsys)
    _run(
        [
            "plan",
            "update",
            "--period",
            "2026-07",
            "--category",
            "Освіта/Школа",
            "--currency",
            "UAH",
            "--kind",
            "baseline",
            "--amount",
            "0",
            "--db",
            str(empty_db),
        ],
        capsys,
    )
    rc, out, err = _run(["plan", "undo", "--period", "2026-07", "--db", str(empty_db)], capsys)
    assert rc == 0, err
    assert out["undone"]["op"] == "update"
    amt = (
        sqlite3.connect(empty_db)
        .execute(
            "SELECT amount_minor FROM budget_line bl "
            "JOIN budget b ON b.id = bl.budget_id "
            "WHERE b.period = '2026-07' AND bl.category = 'Освіта/Школа'"
        )
        .fetchone()[0]
    )
    assert amt == -1560000  # restored


def test_cli_plan_cancel_unknown_period(empty_db: Path, capsys: pytest.CaptureFixture[str]) -> None:
    rc, _, err = _run(["plan", "cancel", "--period", "2099-12", "--db", str(empty_db)], capsys)
    assert rc == 1
    assert err["type"] == "NotFound"
