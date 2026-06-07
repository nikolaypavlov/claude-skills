"""``pf-budget import`` end-to-end tests + budget module unit tests.

Covers:
- CSV parsing (Plans + Baseline shapes), with error paths for bad
  headers, bad period, bad currency, bad kind, bad amount.
- Baseline / Plans merging semantics (period filter, override by
  same (category, currency, kind)).
- Levenshtein-based unknown-category suggestions.
- Materialisation: budget + budget_line written, replace on re-run
  for an active budget, refused on closed budget without --force.
- CLI dry-run vs apply, register vs reject of unknowns, error
  payload shape (``details`` with suggestions).
"""

from __future__ import annotations

import csv
import json
import sqlite3
from pathlib import Path

import pytest

from pf_skill.budget_cli import main
from pf_skill.common import budget as bud

# --- helpers -----------------------------------------------------------------


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


def _write_csv(path: Path, header: list[str], rows: list[list[str]]) -> None:
    with path.open("w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow(header)
        for r in rows:
            w.writerow(r)


# --- parse_plans_csv ---------------------------------------------------------


def test_parse_plans_csv_basic(tmp_path: Path) -> None:
    csv_path = tmp_path / "plans.csv"
    _write_csv(
        csv_path,
        ["Period", "Category", "Currency", "Kind", "Amount", "Note"],
        [
            ["2026-06", "Житло/Оренда", "UAH", "baseline", "-19500", ""],
            ["2026-06", "Подорожі/Готелі", "UAH", "one_time", "-13000", "IF"],
            ["2026-07", "Підписки/AI", "UAH", "baseline", "-5300", ""],
        ],
    )
    rows = bud.parse_plans_csv(csv_path)
    assert len(rows) == 3
    by_cat = {r.category: r for r in rows}
    assert by_cat["Житло/Оренда"].amount_minor == -1_950_000
    assert by_cat["Житло/Оренда"].currency_code == 980
    assert by_cat["Житло/Оренда"].kind == "baseline"
    assert by_cat["Подорожі/Готелі"].note == "IF"
    assert by_cat["Підписки/AI"].period == "2026-07"


def test_parse_plans_csv_missing_required_column(tmp_path: Path) -> None:
    csv_path = tmp_path / "plans.csv"
    _write_csv(
        csv_path,
        ["Period", "Category", "Currency", "Amount"],  # missing Kind
        [["2026-06", "Test", "UAH", "-100"]],
    )
    with pytest.raises(bud.BudgetParseError) as exc_info:
        bud.parse_plans_csv(csv_path)
    assert "missing required columns" in str(exc_info.value).lower()
    assert "Kind" in exc_info.value.details["missing"]


def test_parse_plans_csv_bad_period_shape(tmp_path: Path) -> None:
    csv_path = tmp_path / "plans.csv"
    _write_csv(
        csv_path,
        ["Period", "Category", "Currency", "Kind", "Amount"],
        [["2026/06", "Test", "UAH", "baseline", "-100"]],
    )
    with pytest.raises(bud.BudgetParseError):
        bud.parse_plans_csv(csv_path)


def test_parse_plans_csv_bad_currency(tmp_path: Path) -> None:
    csv_path = tmp_path / "plans.csv"
    _write_csv(
        csv_path,
        ["Period", "Category", "Currency", "Kind", "Amount"],
        [["2026-06", "Test", "BTC", "baseline", "-100"]],
    )
    with pytest.raises(bud.BudgetParseError, match="unknown Currency"):
        bud.parse_plans_csv(csv_path)


def test_parse_plans_csv_bad_kind(tmp_path: Path) -> None:
    csv_path = tmp_path / "plans.csv"
    _write_csv(
        csv_path,
        ["Period", "Category", "Currency", "Kind", "Amount"],
        [["2026-06", "Test", "UAH", "lazy", "-100"]],
    )
    with pytest.raises(bud.BudgetParseError, match="Kind 'lazy'"):
        bud.parse_plans_csv(csv_path)


def test_parse_plans_csv_bad_amount(tmp_path: Path) -> None:
    csv_path = tmp_path / "plans.csv"
    _write_csv(
        csv_path,
        ["Period", "Category", "Currency", "Kind", "Amount"],
        [["2026-06", "Test", "UAH", "baseline", "not-a-number"]],
    )
    with pytest.raises(bud.BudgetParseError, match="not numeric"):
        bud.parse_plans_csv(csv_path)


def test_parse_plans_csv_extra_columns_tolerated(tmp_path: Path) -> None:
    """Sheets often add helper columns. Extras must not break parse."""
    csv_path = tmp_path / "plans.csv"
    _write_csv(
        csv_path,
        ["Period", "Category", "Currency", "Kind", "Amount", "Note", "Source"],
        [["2026-06", "Test", "UAH", "baseline", "-100", "n", "manual"]],
    )
    rows = bud.parse_plans_csv(csv_path)
    assert len(rows) == 1


def test_parse_baseline_csv_rejects_one_time_kind(tmp_path: Path) -> None:
    csv_path = tmp_path / "baseline.csv"
    _write_csv(
        csv_path,
        ["Category", "Currency", "Kind", "Note", "Monthly target"],
        [["Test", "UAH", "one_time", "", "-1000"]],
    )
    with pytest.raises(bud.BudgetParseError, match="must not contain"):
        bud.parse_baseline_csv(csv_path, "2026-06")


# --- Levenshtein + suggestions -----------------------------------------------


def test_levenshtein_basic() -> None:
    assert bud.levenshtein("Patreon", "Patreon") == 0
    assert bud.levenshtein("Patreon", "Patreom") == 1
    assert bud.levenshtein("", "abc") == 3
    assert bud.levenshtein("abc", "") == 3


def test_suggest_categories_top_n() -> None:
    cands = ["Підписки/AI", "Підписки/Інше", "Покупки/Інше", "Зв'язок"]
    out = bud.suggest_categories("Підиски/AI", cands, top_n=3)
    assert len(out) == 3
    # Closest match wins
    assert out[0][0] == "Підписки/AI"
    assert out[0][1] == 1


# --- merge_baseline_plans ----------------------------------------------------


def test_merge_baseline_plans_period_filter() -> None:
    baseline = [
        bud.PlanRow("2026-06", "A", 980, "baseline", -100),
        bud.PlanRow("2026-06", "B", 980, "baseline", -200),
    ]
    plans = [
        bud.PlanRow("2026-06", "C", 980, "one_time", -500),
        bud.PlanRow("2026-07", "C", 980, "one_time", -800),  # different period
    ]
    out = bud.merge_baseline_plans(baseline, plans, period="2026-06")
    assert [r.category for r in out] == ["A", "B", "C"]


def test_merge_baseline_plans_override_same_key() -> None:
    """A Plans row with kind=baseline overrides a Baseline row for the
    same (category, currency, kind)."""
    baseline = [bud.PlanRow("2026-06", "Rent", 980, "baseline", -2000000)]
    plans = [bud.PlanRow("2026-06", "Rent", 980, "baseline", -1950000)]  # special
    out = bud.merge_baseline_plans(baseline, plans, period="2026-06")
    assert len(out) == 1
    assert out[0].amount_minor == -1950000


# --- validate_categories -----------------------------------------------------


def test_validate_categories_known_pass_through(empty_db: Path) -> None:
    from pf_skill.common.store import open_db

    conn = open_db(empty_db)
    conn.execute(
        "INSERT INTO category_registry (category, declared_at, declared_via) VALUES ('A', 0, 'cli')"
    )
    rows = [bud.PlanRow("2026-06", "A", 980, "baseline", -100)]
    result = bud.validate_categories(rows, conn)
    assert result.unknown == []


def test_validate_categories_unknown_with_suggestions(empty_db: Path) -> None:
    from pf_skill.common.store import open_db

    conn = open_db(empty_db)
    conn.execute(
        "INSERT INTO tx_category (tx_id, category, set_at, set_by) "
        "VALUES ('t1', 'Підписки/AI', 0, 'rule')"
    )
    rows = [bud.PlanRow("2026-06", "Підиски/AI", 980, "baseline", -100)]
    result = bud.validate_categories(rows, conn)
    assert len(result.unknown) == 1
    cat, suggestions = result.unknown[0]
    assert cat == "Підиски/AI"
    assert suggestions[0][0] == "Підписки/AI"


# --- materialise_budget ------------------------------------------------------


def test_materialise_budget_creates_per_currency(empty_db: Path) -> None:
    from pf_skill.common.store import open_db

    conn = open_db(empty_db)
    rows = [
        bud.PlanRow("2026-06", "A", 980, "baseline", -19500_00),
        bud.PlanRow("2026-06", "B", 840, "baseline", -1700_00),
    ]
    result = bud.materialise_budget(conn, period="2026-06", rows=rows, source="t")
    assert 980 in result.by_currency
    assert 840 in result.by_currency
    n_uah = conn.execute(
        "SELECT COUNT(*) FROM budget_line bl "
        "JOIN budget b ON b.id = bl.budget_id "
        "WHERE b.currency_code = 980"
    ).fetchone()[0]
    assert n_uah == 1


def test_materialise_budget_replaces_active(empty_db: Path) -> None:
    from pf_skill.common.store import open_db

    conn = open_db(empty_db)
    rows_v1 = [bud.PlanRow("2026-06", "A", 980, "baseline", -100)]
    bud.materialise_budget(conn, period="2026-06", rows=rows_v1, source="v1")
    rows_v2 = [
        bud.PlanRow("2026-06", "A", 980, "baseline", -150),
        bud.PlanRow("2026-06", "B", 980, "one_time", -50),
    ]
    result = bud.materialise_budget(conn, period="2026-06", rows=rows_v2, source="v2")
    assert result.by_currency[980]["lines_replaced"] == 1
    assert result.by_currency[980]["lines_added"] == 2
    total = conn.execute(
        "SELECT SUM(amount_minor) FROM budget_line bl "
        "JOIN budget b ON b.id = bl.budget_id "
        "WHERE b.currency_code = 980"
    ).fetchone()[0]
    assert total == -200


def test_materialise_budget_refuses_closed(empty_db: Path) -> None:
    from pf_skill.common.store import open_db

    conn = open_db(empty_db)
    bud.materialise_budget(
        conn,
        period="2026-05",
        rows=[bud.PlanRow("2026-05", "A", 980, "baseline", -100)],
        source="t",
    )
    conn.isolation_level = None
    conn.execute("UPDATE budget SET status = 'closed' WHERE period = '2026-05'")
    with pytest.raises(bud.BudgetParseError, match="closed"):
        bud.materialise_budget(
            conn,
            period="2026-05",
            rows=[bud.PlanRow("2026-05", "A", 980, "baseline", -999)],
            source="t",
        )


# --- CLI: import end-to-end --------------------------------------------------


def _plans_csv(tmp_path: Path, rows: list[list[str]]) -> Path:
    p = tmp_path / "plans.csv"
    _write_csv(
        p,
        ["Period", "Category", "Currency", "Kind", "Amount", "Note"],
        rows,
    )
    return p


def test_cli_import_reject_lists_unknown_with_suggestions(
    empty_db: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    conn = sqlite3.connect(empty_db)
    # Bring schema up via pf-query categories (or any open_db call).
    _run(["list-categories", "--db", str(empty_db)], capsys)
    conn = sqlite3.connect(empty_db)
    try:
        conn.execute(
            "INSERT INTO tx_category (tx_id, category, set_at, set_by) "
            "VALUES ('t1', 'Підписки/AI', 0, 'rule')"
        )
        conn.commit()
    finally:
        conn.close()
    csv_path = _plans_csv(
        tmp_path,
        [["2026-06", "Підиски/AI", "UAH", "baseline", "-5300", ""]],  # typo
    )
    rc, _, err = _run(
        ["import", str(csv_path), "--period", "2026-06", "--db", str(empty_db)],
        capsys,
    )
    assert rc == 1
    assert err["type"] == "UnknownCategories"
    assert err["details"]["unknown"][0]["category"] == "Підиски/AI"
    suggestions = err["details"]["unknown"][0]["suggestions"]
    assert suggestions[0]["candidate"] == "Підписки/AI"


def test_cli_import_register_adds_to_registry_and_writes(
    empty_db: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    csv_path = _plans_csv(
        tmp_path,
        [["2026-06", "Покупки/Сад", "UAH", "one_time", "-1500", "Дача"]],
    )
    rc, out, err = _run(
        [
            "import",
            str(csv_path),
            "--period",
            "2026-06",
            "--unknown-categories",
            "register",
            "--db",
            str(empty_db),
        ],
        capsys,
    )
    assert rc == 0, err
    assert out["new_categories_registered"] == ["Покупки/Сад"]
    assert out["rows_imported"] == 1
    assert out["by_currency"][str(980)]["lines_added"] == 1


def test_cli_import_dry_run_does_not_write(
    empty_db: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    csv_path = _plans_csv(
        tmp_path,
        [["2026-06", "Покупки/Сад", "UAH", "one_time", "-1500", ""]],
    )
    rc, out, err = _run(
        [
            "import",
            str(csv_path),
            "--period",
            "2026-06",
            "--unknown-categories",
            "register",
            "--dry-run",
            "--db",
            str(empty_db),
        ],
        capsys,
    )
    assert rc == 0, err
    assert out["dry_run"] is True
    assert out["rows_parsed"] == 1
    conn = sqlite3.connect(empty_db)
    try:
        n = conn.execute("SELECT COUNT(*) FROM budget").fetchone()[0]
        m = conn.execute("SELECT COUNT(*) FROM category_registry").fetchone()[0]
    finally:
        conn.close()
    assert n == 0  # no budget written
    assert m == 0  # registry not touched


def test_cli_import_filters_period_from_multiperiod_csv(
    empty_db: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """The same Plans sheet can contain rows for many months; --period
    must filter to the target month only."""
    csv_path = _plans_csv(
        tmp_path,
        [
            ["2026-06", "Покупки/Сад", "UAH", "one_time", "-100", ""],
            ["2026-07", "Покупки/Сад", "UAH", "one_time", "-200", ""],
            ["2026-08", "Покупки/Сад", "UAH", "one_time", "-300", ""],
        ],
    )
    rc, out, err = _run(
        [
            "import",
            str(csv_path),
            "--period",
            "2026-07",
            "--unknown-categories",
            "register",
            "--db",
            str(empty_db),
        ],
        capsys,
    )
    assert rc == 0, err
    assert out["rows_imported"] == 1
    conn = sqlite3.connect(empty_db)
    try:
        amt = conn.execute(
            "SELECT amount_minor FROM budget_line bl "
            "JOIN budget b ON b.id = bl.budget_id WHERE b.period = '2026-07'"
        ).fetchone()
    finally:
        conn.close()
    assert amt == (-20000,)  # -200 * 100


def test_cli_import_audit_log_written(
    empty_db: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    csv_path = _plans_csv(
        tmp_path,
        [["2026-06", "X", "UAH", "baseline", "-100", ""]],
    )
    rc, out, err = _run(
        [
            "import",
            str(csv_path),
            "--period",
            "2026-06",
            "--unknown-categories",
            "register",
            "--db",
            str(empty_db),
        ],
        capsys,
    )
    assert rc == 0, err
    run_id = out["import_run_id"]
    conn = sqlite3.connect(empty_db)
    try:
        row = conn.execute(
            "SELECT source, period, lines_added, lines_replaced, new_categories "
            "FROM budget_import_run WHERE id = ?",
            (run_id,),
        ).fetchone()
    finally:
        conn.close()
    assert row[1] == "2026-06"
    assert row[2] == 1
    assert row[3] == 0
    assert "X" in row[4]


def test_cli_import_bad_period_arg(
    empty_db: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    csv_path = _plans_csv(
        tmp_path,
        [["2026-06", "X", "UAH", "baseline", "-100", ""]],
    )
    rc, _, err = _run(
        ["import", str(csv_path), "--period", "2026/06", "--db", str(empty_db)],
        capsys,
    )
    assert rc == 1
    assert "YYYY-MM" in err["error"]


def test_cli_import_file_not_found(empty_db: Path, capsys: pytest.CaptureFixture[str]) -> None:
    rc, _, err = _run(
        ["import", "/no/such/path.csv", "--period", "2026-06", "--db", str(empty_db)],
        capsys,
    )
    assert rc == 1
    assert err["type"] == "FileNotFound"
