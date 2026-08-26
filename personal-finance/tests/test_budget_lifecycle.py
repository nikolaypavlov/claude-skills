"""``pf-budget`` lifecycle subcommands: show, diff, list, close,
reopen, delete, rename-category."""

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


def _seed_budget(db: Path, period: str = "2026-06") -> None:
    """Plant one UAH budget with three lines on the given period."""
    conn = open_db(db)
    bud.materialise_budget(
        conn,
        period=period,
        rows=[
            bud.PlanRow(period, "Їжа/Ресторани", 980, "baseline", -900000),
            bud.PlanRow(period, "Їжа/Продукти", 980, "baseline", -800000),
            bud.PlanRow(period, "Подорожі/Готелі", 980, "one_time", -1260000),
        ],
        source="seed",
    )
    conn.close()


# --- show -------------------------------------------------------------------


def test_show_returns_budget_with_lines(empty_db: Path, capsys: pytest.CaptureFixture[str]) -> None:
    _seed_budget(empty_db)
    rc, out, err = _run(["show", "--period", "2026-06", "--db", str(empty_db)], capsys)
    assert rc == 0, err
    assert len(out["budgets"]) == 1
    b = out["budgets"][0]
    assert b["currency_code"] == 980
    assert b["line_count"] == 3
    cats = [line["category"] for line in b["lines"]]
    assert "Подорожі/Готелі" in cats


def test_show_no_budget_for_period(empty_db: Path, capsys: pytest.CaptureFixture[str]) -> None:
    rc, out, err = _run(["show", "--period", "2026-06", "--db", str(empty_db)], capsys)
    assert rc == 0, err
    assert out["budgets"] == []
    assert "no budget" in out["warning"]


def test_show_filters_by_currency(empty_db: Path, capsys: pytest.CaptureFixture[str]) -> None:
    _seed_budget(empty_db)
    # add a USD budget so we have two
    conn = open_db(empty_db)
    bud.materialise_budget(
        conn,
        period="2026-06",
        rows=[bud.PlanRow("2026-06", "Investments", 840, "baseline", -170000)],
        source="seed-usd",
    )
    conn.close()
    rc, out, err = _run(
        ["show", "--period", "2026-06", "--currency", "USD", "--db", str(empty_db)],
        capsys,
    )
    assert rc == 0, err
    assert len(out["budgets"]) == 1
    assert out["budgets"][0]["currency_code"] == 840


# --- list -------------------------------------------------------------------


def test_list_includes_status_and_totals(
    empty_db: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    _seed_budget(empty_db, "2026-06")
    _seed_budget(empty_db, "2026-05")
    rc, out, err = _run(["list", "--db", str(empty_db)], capsys)
    assert rc == 0, err
    assert out["count"] == 2
    periods = [b["period"] for b in out["budgets"]]
    assert periods == ["2026-06", "2026-05"]  # DESC ordering by period


# --- close + reopen ---------------------------------------------------------


def test_close_then_reopen_flow(empty_db: Path, capsys: pytest.CaptureFixture[str]) -> None:
    _seed_budget(empty_db, "2026-05")
    rc, out, err = _run(["close", "--period", "2026-05", "--db", str(empty_db)], capsys)
    assert rc == 0, err
    assert out["changed"][0]["new_status"] == "closed"

    # Re-import should fail without --force after closing
    rc, _, err = _run(["close", "--period", "2026-05", "--db", str(empty_db)], capsys)
    # second close on already-closed budget is a no-op (no rows changed)
    # set_status returns empty -> CLI reports NotFound-style? we want it
    # to succeed silently. let's check the contract here:
    # current implementation raises NotFound only when no rows matched
    # at all. A no-op for already-closed returns the matching budget
    # with no entries in `changed`. Verify behaviour.
    rc, out, err = _run(["close", "--period", "2026-05", "--db", str(empty_db)], capsys)
    # No-op close should succeed with empty changed list - the budget
    # exists, just nothing to flip.
    assert rc == 0
    assert out["changed"] == []

    rc, out, err = _run(
        ["reopen", "--period", "2026-05", "--reason", "fix may", "--db", str(empty_db)],
        capsys,
    )
    assert rc == 0
    assert out["changed"][0]["new_status"] == "active"


def test_close_unknown_period_404(empty_db: Path, capsys: pytest.CaptureFixture[str]) -> None:
    rc, _, err = _run(["close", "--period", "2099-12", "--db", str(empty_db)], capsys)
    assert rc == 1
    assert err["type"] == "NotFound"


# --- delete -----------------------------------------------------------------


def test_delete_active_budget(empty_db: Path, capsys: pytest.CaptureFixture[str]) -> None:
    _seed_budget(empty_db, "2026-04")
    rc, out, err = _run(["delete", "--period", "2026-04", "--db", str(empty_db)], capsys)
    assert rc == 0, err
    conn = sqlite3.connect(empty_db)
    try:
        n_b = conn.execute("SELECT COUNT(*) FROM budget").fetchone()[0]
        n_l = conn.execute("SELECT COUNT(*) FROM budget_line").fetchone()[0]
    finally:
        conn.close()
    assert n_b == 0
    assert n_l == 0  # cascade delete


def test_delete_closed_refused_without_force(
    empty_db: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    _seed_budget(empty_db, "2026-04")
    _run(["close", "--period", "2026-04", "--db", str(empty_db)], capsys)
    rc, _, err = _run(["delete", "--period", "2026-04", "--db", str(empty_db)], capsys)
    assert rc == 1
    assert err["type"] == "ClosedBudget"


def test_delete_closed_with_force_succeeds(
    empty_db: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    _seed_budget(empty_db, "2026-04")
    _run(["close", "--period", "2026-04", "--db", str(empty_db)], capsys)
    rc, _, err = _run(
        ["delete", "--period", "2026-04", "--force", "--db", str(empty_db)],
        capsys,
    )
    assert rc == 0, err


# --- diff -------------------------------------------------------------------


def test_diff_joins_with_actuals_via_category_resolution(
    mixed_currency_db: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """A budget line on a category that an actual tx is pinned to
    should show pct_used != None. Use the mixed-currency fixture so
    transactions exist; manually pin a couple to known categories."""
    conn = open_db(mixed_currency_db)
    # Pin the Patreon tx (-21232 UAH) to Підписки/Інше and the USD AWS tx
    # (-5500 USD) to Підписки/Інше USD account.
    conn.execute(
        "INSERT INTO tx_category (tx_id, category, set_at, set_by) VALUES "
        "('uah_patreon', 'Підписки/Інше', 1700000050, 'manual'), "
        "('usd_aws',    'Підписки/Cloud', 1700003050, 'manual')"
    )
    # Pin tx into the May 2024 period that we'll diff against.
    # tx ts = 1_700_000_000 (~Nov 2023); we need a period that matches.
    # 1_700_000_000 → 2023-11-14 UTC → period 2023-11.
    bud.materialise_budget(
        conn,
        period="2023-11",
        rows=[
            bud.PlanRow("2023-11", "Підписки/Інше", 980, "baseline", -25000),
            bud.PlanRow("2023-11", "Підписки/Cloud", 840, "baseline", -10000),
        ],
        source="seed",
    )
    conn.close()

    rc, out, err = _run(["diff", "--period", "2023-11", "--db", str(mixed_currency_db)], capsys)
    assert rc == 0, err
    blocks_by_cur = {b["currency_code"]: b for b in out["blocks"]}
    assert 980 in blocks_by_cur and 840 in blocks_by_cur

    uah = blocks_by_cur[980]
    cats = {line["category"]: line for line in uah["lines"]}
    assert cats["Підписки/Інше"]["actual_minor"] == -21232


def test_diff_surfaces_actuals_with_no_budget_line(
    mixed_currency_db: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    conn = open_db(mixed_currency_db)
    conn.execute(
        "INSERT INTO tx_category (tx_id, category, set_at, set_by) VALUES "
        "('uah_patreon', 'Підписки/Інше', 1700000050, 'manual')"
    )
    # Empty budget for the period (UAH but no Підписки/Інше line)
    bud.materialise_budget(
        conn,
        period="2023-11",
        rows=[bud.PlanRow("2023-11", "Other", 980, "baseline", -1000)],
        source="seed",
    )
    conn.close()
    rc, out, err = _run(["diff", "--period", "2023-11", "--db", str(mixed_currency_db)], capsys)
    assert rc == 0, err
    uah = next(b for b in out["blocks"] if b["currency_code"] == 980)
    cats = {line["category"]: line for line in uah["lines"]}
    patreon = cats["Підписки/Інше"]
    assert patreon["in_budget"] is False
    assert patreon["target_minor"] == 0
    assert patreon["actual_minor"] == -21232


def test_diff_totals_split_spend_and_income(
    mono_only_db: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Totals must keep real spend and income separate. The legacy
    ``actual_minor`` nets income into the spend number (the exact trap
    that confused reconciliation); the split fields are the fix."""
    conn = open_db(mono_only_db)
    # mono_t1 -25000 (spend), mono_t2 -150000 (spend), mono_t3 +500000 (income)
    conn.execute(
        "INSERT INTO tx_category (tx_id, category, set_at, set_by) VALUES "
        "('mono_t1', 'Їжа/Кава', 1700000050, 'manual'), "
        "('mono_t2', 'Їжа/Продукти', 1700001050, 'manual'), "
        "('mono_t3', 'Дохід/Зарплата', 1700002050, 'manual')"
    )
    bud.materialise_budget(
        conn,
        period="2023-11",
        rows=[
            bud.PlanRow("2023-11", "Їжа/Кава", 980, "baseline", -30000),
            bud.PlanRow("2023-11", "Їжа/Продукти", 980, "baseline", -200000),
        ],
        source="seed",
    )
    conn.close()
    rc, out, err = _run(["diff", "--period", "2023-11", "--db", str(mono_only_db)], capsys)
    assert rc == 0, err
    uah = next(b for b in out["blocks"] if b["currency_code"] == 980)
    t = uah["totals"]
    assert t["real_spend_minor"] == -175000  # spend rows only, income excluded
    assert t["income_minor"] == 500000  # salary
    # remaining = spend_target(-230000) - real_spend(-175000)
    assert t["remaining_minor"] == -55000
    # legacy net still present and equals spend+income - which is exactly
    # why it is misleading on its own.
    assert t["actual_minor"] == 325000


# --- rename-category --------------------------------------------------------


def test_rename_category_updates_budget_lines(
    empty_db: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    _seed_budget(empty_db, "2026-06")
    rc, out, err = _run(
        [
            "rename-category",
            "--from",
            "Подорожі/Готелі",
            "--to",
            "Подорожі/Hotel",
            "--update",
            "budget_line",
            "--db",
            str(empty_db),
        ],
        capsys,
    )
    assert rc == 0, err
    assert out["counts"]["budget_line"] == 1
    conn = sqlite3.connect(empty_db)
    try:
        row = conn.execute(
            "SELECT COUNT(*) FROM budget_line WHERE category = 'Подорожі/Hotel'"
        ).fetchone()
    finally:
        conn.close()
    assert row == (1,)


def test_rename_category_multi_table(empty_db: Path, capsys: pytest.CaptureFixture[str]) -> None:
    """Multiple tables in --update get updated atomically. tx_category
    not exercised yet (no tx in empty_db) but should still report 0."""
    _seed_budget(empty_db)
    conn = sqlite3.connect(empty_db)
    try:
        conn.execute(
            "INSERT INTO category_registry "
            "(category, declared_at, declared_via) VALUES ('Подорожі/Готелі', 0, 'cli')"
        )
        conn.commit()
    finally:
        conn.close()
    rc, out, err = _run(
        [
            "rename-category",
            "--from",
            "Подорожі/Готелі",
            "--to",
            "Подорожі/Hotel",
            "--update",
            "budget_line,category_registry",
            "--db",
            str(empty_db),
        ],
        capsys,
    )
    assert rc == 0, err
    assert out["counts"]["budget_line"] == 1
    assert out["counts"]["category_registry"] == 1


def test_rename_category_rejects_unknown_table(
    empty_db: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    rc, _, err = _run(
        [
            "rename-category",
            "--from",
            "A",
            "--to",
            "B",
            "--update",
            "secret_table",
            "--db",
            str(empty_db),
        ],
        capsys,
    )
    assert rc == 1
    assert "not allowed" in err["error"]


def test_rename_category_rejects_identical_names(
    empty_db: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    rc, _, err = _run(
        [
            "rename-category",
            "--from",
            "X",
            "--to",
            "X",
            "--update",
            "budget_line",
            "--db",
            str(empty_db),
        ],
        capsys,
    )
    assert rc == 1
    assert "identical" in err["error"]


def test_diff_totals_separate_gross_outflow_from_non_income_inflow(
    mono_only_db: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """A positive row OUTSIDE ``Дохід/*`` nets into ``real_spend_minor``
    and understates spend by exactly its amount.

    Real case: a maturing bond credits ``Інвестиції/Облігації``. It is
    neither income nor a refund - it converts an asset to cash - but the
    spend figure absorbs it silently, and a month at 96% of plan reads as
    82%. ``gross_outflow_minor`` is the honest number; a non-zero
    ``other_inflow_minor`` is the signal to use it.
    """
    conn = open_db(mono_only_db)
    # mono_t3 is +500000, categorised OUTSIDE Дохід/* this time.
    conn.execute(
        "INSERT INTO tx_category (tx_id, category, set_at, set_by) VALUES "
        "('mono_t1', 'Їжа/Кава', 1700000050, 'manual'), "
        "('mono_t2', 'Їжа/Продукти', 1700001050, 'manual'), "
        "('mono_t3', 'Інвестиції/Облігації', 1700002050, 'manual')"
    )
    bud.materialise_budget(
        conn,
        period="2023-11",
        rows=[
            bud.PlanRow("2023-11", "Їжа/Кава", 980, "baseline", -30000),
            bud.PlanRow("2023-11", "Їжа/Продукти", 980, "baseline", -200000),
        ],
        source="seed",
    )
    conn.close()
    rc, out, err = _run(["diff", "--period", "2023-11", "--db", str(mono_only_db)], capsys)
    assert rc == 0, err
    t = next(b for b in out["blocks"] if b["currency_code"] == 980)["totals"]

    # Nothing landed on Дохід/*, so the income figure is silent about it.
    assert t["income_minor"] == 0
    # The redemption nets in and turns "spend" positive - the bug.
    assert t["real_spend_minor"] == 325000
    # The split tells the truth: 175000 left, 500000 arrived.
    assert t["gross_outflow_minor"] == -175000
    assert t["other_inflow_minor"] == 500000
    # Documented reconciliation between the three.
    assert t["real_spend_minor"] == t["gross_outflow_minor"] + t["other_inflow_minor"]


def test_diff_totals_other_inflow_zero_on_an_ordinary_month(
    mono_only_db: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """With only outflows and ``Дохід/*`` rows, the split adds nothing and
    ``gross_outflow_minor`` equals ``real_spend_minor``."""
    conn = open_db(mono_only_db)
    conn.execute(
        "INSERT INTO tx_category (tx_id, category, set_at, set_by) VALUES "
        "('mono_t1', 'Їжа/Кава', 1700000050, 'manual'), "
        "('mono_t2', 'Їжа/Продукти', 1700001050, 'manual'), "
        "('mono_t3', 'Дохід/Зарплата', 1700002050, 'manual')"
    )
    bud.materialise_budget(
        conn,
        period="2023-11",
        rows=[bud.PlanRow("2023-11", "Їжа/Кава", 980, "baseline", -30000)],
        source="seed",
    )
    conn.close()
    rc, out, err = _run(["diff", "--period", "2023-11", "--db", str(mono_only_db)], capsys)
    assert rc == 0, err
    t = next(b for b in out["blocks"] if b["currency_code"] == 980)["totals"]
    assert t["other_inflow_minor"] == 0
    assert t["gross_outflow_minor"] == t["real_spend_minor"] == -175000
