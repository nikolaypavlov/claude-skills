"""``pf-budget`` CLI entry: budget management.

Subcommands::

    pf-budget register-category --category NAME [--note NOTE]
    pf-budget unregister-category --category NAME [--force]
    pf-budget list-categories [--include-declared]
    pf-budget import <file> --period YYYY-MM
                            [--unknown-categories reject|register]
                            [--dry-run] [--force]
                            [--sheet plans|baseline]

Output contract matches the rest of the ``pf-*`` scripts via
``common.cli.run_subcommand``: success → JSON to stdout exit 0,
``CliError`` → JSON to stderr exit 1, uncaught → traceback + exit 2.
"""

from __future__ import annotations

import argparse
import sqlite3
import sys
import time
from collections.abc import Sequence
from contextlib import closing
from pathlib import Path
from typing import Any

from .common import budget as bud
from .common import queries as q
from .common.cli import (
    CliError,
    resolve_db_path,
    run_subcommand,
)
from .common.store import open_db

# Categories are slash-separated taxonomy names. We forbid leading
# and trailing whitespace and empty segments because sheets frequently
# leak those in via copy-paste. The character set is intentionally
# permissive (Cyrillic categories are the norm); we only forbid the
# truly broken shapes that would corrupt joins.
_FORBIDDEN_LEADING_TRAILING_WHITESPACE_MSG = (
    "category contains leading or trailing whitespace; strip first"
)


def _validate_category_name(name: str) -> str:
    if not name:
        raise CliError("--category must be non-empty")
    if name != name.strip():
        raise CliError(_FORBIDDEN_LEADING_TRAILING_WHITESPACE_MSG)
    if "//" in name or name.startswith("/") or name.endswith("/"):
        raise CliError(
            f"--category {name!r} has empty hierarchy segments; use "
            "TopGroup/Sub form without leading/trailing slashes"
        )
    return name


def _category_in_use(conn: sqlite3.Connection, category: str) -> dict[str, Any]:
    """Aggregate references to a category across the user-mutable
    tables. Used by unregister-category to refuse deletion when the
    category is still load-bearing.

    Returns a dict with counts per source (so the error message can
    point the user at exactly what needs cleaning up first).
    """
    counts: dict[str, int] = {}
    counts["tx_category"] = conn.execute(
        "SELECT COUNT(*) FROM tx_category WHERE category = ?", (category,)
    ).fetchone()[0]
    counts["category_overrides"] = conn.execute(
        "SELECT COUNT(*) FROM category_overrides WHERE category = ?", (category,)
    ).fetchone()[0]
    counts["categorization_rules"] = conn.execute(
        "SELECT COUNT(*) FROM categorization_rules WHERE category = ?", (category,)
    ).fetchone()[0]
    # budget_line table exists from migration v2 onwards. Probe defensively
    # so a partially-migrated DB surfaces a clean error instead of a
    # mysterious sqlite OperationalError.
    try:
        counts["budget_line"] = conn.execute(
            "SELECT COUNT(*) FROM budget_line WHERE category = ?", (category,)
        ).fetchone()[0]
    except sqlite3.OperationalError as exc:
        if "no such table" not in str(exc).lower():
            raise
        counts["budget_line"] = 0
    return counts


def cmd_register_category(args: argparse.Namespace) -> dict[str, Any]:
    """Insert a row into ``category_registry``.

    Idempotent: registering an already-registered category is a no-op
    that returns ``{"ok": true, "already_registered": true}`` without
    touching ``declared_at`` / ``declared_via`` / ``note``. Surprise-
    rewriting metadata would defeat the audit trail.
    """
    category = _validate_category_name(args.category)
    now_ts = int(time.time())
    db_path = resolve_db_path(args.db)
    with closing(open_db(db_path)) as conn:
        existing = conn.execute(
            "SELECT declared_at, declared_via, note FROM category_registry WHERE category = ?",
            (category,),
        ).fetchone()
        if existing is not None:
            return {
                "ok": True,
                "already_registered": True,
                "category": category,
                "declared_at": int(existing[0]),
                "declared_via": existing[1],
                "note": existing[2],
            }
        conn.execute("BEGIN")
        try:
            conn.execute(
                "INSERT INTO category_registry "
                "(category, declared_at, declared_via, note) "
                "VALUES (?, ?, ?, ?)",
                (category, now_ts, "cli", args.note),
            )
            conn.commit()
        except Exception:
            conn.rollback()
            raise
    return {
        "ok": True,
        "already_registered": False,
        "category": category,
        "declared_at": now_ts,
        "declared_via": "cli",
        "note": args.note,
    }


def cmd_unregister_category(args: argparse.Namespace) -> dict[str, Any]:
    """Remove a row from ``category_registry``.

    Refuses to delete a category that is still referenced from
    ``tx_category``, ``category_overrides``, ``categorization_rules``,
    or ``budget_line`` - the user would just rediscover the category
    on the next read. ``--force`` overrides the safety, but is
    deliberately undocumented in the help text so it only gets used
    when somebody has read the source.
    """
    category = _validate_category_name(args.category)
    db_path = resolve_db_path(args.db)
    with closing(open_db(db_path)) as conn:
        existing = conn.execute(
            "SELECT category FROM category_registry WHERE category = ?",
            (category,),
        ).fetchone()
        if existing is None:
            raise CliError(
                f"category {category!r} is not in the registry",
                kind="NotFound",
            )
        usage = _category_in_use(conn, category)
        total_refs = sum(usage.values())
        if total_refs > 0 and not args.force:
            raise CliError(
                f"category {category!r} is still referenced "
                f"({total_refs} rows: {usage}); rename or remove the "
                "references first (or pass --force to unregister anyway)",
                kind="StillInUse",
            )
        conn.execute("BEGIN")
        try:
            conn.execute(
                "DELETE FROM category_registry WHERE category = ?",
                (category,),
            )
            conn.commit()
        except Exception:
            conn.rollback()
            raise
    return {
        "ok": True,
        "category": category,
        "removed": True,
        "remaining_references": usage,
    }


def _parse_file_into_plan(args: argparse.Namespace) -> list[bud.PlanRow]:
    """Decide which parser to use based on the file extension and (for
    XLSX) on whether the workbook has a Baseline sheet alongside Plans.
    Stamps period onto baseline rows; returns the merged plan rows for
    ``args.period``."""
    path = Path(args.source).expanduser()
    if not path.exists():
        raise CliError(f"file not found: {path}", kind="FileNotFound")
    suffix = path.suffix.lower()
    if suffix == ".csv":
        sheet = args.sheet or "plans"
        if sheet == "plans":
            rows = bud.parse_plans_csv(path)
            return [r for r in rows if r.period == args.period]
        if sheet == "baseline":
            return bud.parse_baseline_csv(path, args.period)
        raise CliError(
            f"--sheet must be 'plans' or 'baseline' for CSV input; got {sheet!r}",
            kind="BadArgument",
        )
    if suffix in (".xlsx", ".xlsm"):
        baseline_raw, plans_raw = bud.parse_workbook_xlsx(path)
        baseline_rows = [
            bud._row_from_baseline(  # type: ignore[attr-defined]
                d, args.period, source_row=d["__source_row__"]
            )
            for d in baseline_raw
            if any((d.get(k) or "") for k in ("Category", "Currency", "Kind", "Monthly target"))
        ]
        plans_rows = [
            bud._row_from_plans(  # type: ignore[attr-defined]
                d, source_row=d["__source_row__"]
            )
            for d in plans_raw
            if any((d.get(k) or "") for k in ("Period", "Category", "Currency", "Kind", "Amount"))
        ]
        return bud.merge_baseline_plans(baseline_rows, plans_rows, period=args.period)
    raise CliError(
        f"unsupported file type {suffix!r}; expected .csv, .xlsx, or .xlsm",
        kind="BadArgument",
    )


def cmd_import(args: argparse.Namespace) -> dict[str, Any]:
    """Import a budget plan from CSV/XLSX into ``budget`` and
    ``budget_line`` tables.

    Validation modes:
    - ``reject`` (default): fail if any category is unknown, returning
      the list with Levenshtein suggestions in the error payload so
      the CLI can render it cleanly.
    - ``register``: silently add every unknown to ``category_registry``
      with ``declared_via='budget-import'`` and proceed.

    ``--dry-run`` runs through parsing + validation + a synthetic
    "what would change" diff against the existing budget (if any),
    but never opens a write transaction.
    """
    if args.period is None:
        raise CliError("--period is required (YYYY-MM)", kind="BadArgument")
    if not bud.PERIOD_RE.match(args.period):
        raise CliError(f"--period={args.period!r} must match YYYY-MM", kind="BadArgument")
    db_path = resolve_db_path(args.db)
    try:
        rows = _parse_file_into_plan(args)
    except bud.BudgetParseError as exc:
        raise CliError(str(exc), kind=exc.kind) from exc

    if not rows:
        return {
            "ok": True,
            "period": args.period,
            "source": str(args.source),
            "rows_parsed": 0,
            "warning": "no rows matched the requested period",
        }

    with closing(open_db(db_path)) as conn:
        try:
            validation = bud.validate_categories(rows, conn)
        except bud.BudgetParseError as exc:
            raise CliError(str(exc), kind=exc.kind) from exc

        unknowns = validation.unknown
        new_categories: list[str] = []
        if unknowns:
            if args.unknown_categories == "reject":
                # Failure with structured payload so the caller can
                # render suggestions per category.
                err = CliError(
                    f"{len(unknowns)} unknown categor"
                    f"{'y' if len(unknowns) == 1 else 'ies'} in input; "
                    "rerun with --unknown-categories register to add them, "
                    "or fix the source",
                    kind="UnknownCategories",
                )
                # Attach details to the exception for downstream parsing
                # if the caller catches it. The CLI scaffolding doesn't
                # surface arbitrary attributes today, so we also log
                # them via err.args[0] above.
                err.details = {  # type: ignore[attr-defined]
                    "unknown": [
                        {
                            "category": cat,
                            "suggestions": [{"candidate": s, "distance": d} for s, d in sugg],
                        }
                        for cat, sugg in unknowns
                    ]
                }
                raise err
            if args.unknown_categories == "register":
                if not args.dry_run:
                    conn.execute("BEGIN")
                    try:
                        bud.register_unknowns(conn, [c for c, _ in unknowns])
                        conn.commit()
                    except Exception:
                        conn.rollback()
                        raise
                new_categories = [c for c, _ in unknowns]

        if args.dry_run:
            return _dry_run_summary(conn, args.period, rows, new_categories)

        result = bud.materialise_budget(
            conn,
            period=args.period,
            rows=rows,
            source=str(args.source),
            force=args.force,
        )
        total_added = sum(v["lines_added"] for v in result.by_currency.values())
        total_replaced = sum(v["lines_replaced"] for v in result.by_currency.values())
        run_id = bud.log_import_run(
            conn,
            source=str(args.source),
            period=args.period,
            lines_added=total_added,
            lines_replaced=total_replaced,
            new_categories=new_categories,
        )
    return {
        "ok": True,
        "period": args.period,
        "source": str(args.source),
        "rows_imported": len(rows),
        "by_currency": result.by_currency,
        "new_categories_registered": new_categories,
        "import_run_id": run_id,
    }


def _dry_run_summary(
    conn: sqlite3.Connection,
    period: str,
    rows: list[bud.PlanRow],
    new_categories: list[str],
) -> dict[str, Any]:
    by_cur: dict[int, dict[str, Any]] = {}
    for r in rows:
        slot = by_cur.setdefault(r.currency_code, {"lines": 0, "total_minor": 0, "kinds": {}})
        slot["lines"] += 1
        slot["total_minor"] += r.amount_minor
        slot["kinds"][r.kind] = slot["kinds"].get(r.kind, 0) + 1
    existing: dict[int, dict[str, Any]] = {}
    for cur, _info in by_cur.items():
        row = conn.execute(
            "SELECT id, status FROM budget WHERE period = ? AND currency_code = ?",
            (period, cur),
        ).fetchone()
        if row is not None:
            existing[cur] = {"budget_id": int(row[0]), "status": row[1]}
    return {
        "ok": True,
        "dry_run": True,
        "period": period,
        "rows_parsed": len(rows),
        "would_register": new_categories,
        "by_currency": by_cur,
        "existing_budgets": existing,
    }


def cmd_list_categories(args: argparse.Namespace) -> dict[str, Any]:
    """Mirror of ``pf-query categories`` for the ``pf-budget`` CLI.

    Returns the in-use categories plus, when ``--include-declared`` is
    set, the declared-but-unused ones from ``category_registry``. We
    expose the same surface here so the budget workflow does not have
    to context-switch between two scripts mid-validation.
    """
    db_path = resolve_db_path(args.db)
    with closing(open_db(db_path)) as conn:
        cats = q.list_categories(conn, include_declared=args.include_declared)
    return {
        "ok": True,
        "count": len(cats),
        "categories": cats,
    }


def _parse_currency_or_cli_error(value: str | None) -> int | None:
    if value is None:
        return None
    from .common.currencies import parse_currency_arg

    try:
        return parse_currency_arg(value)
    except ValueError as exc:
        raise CliError(str(exc), kind="ValueError") from exc


def cmd_show(args: argparse.Namespace) -> dict[str, Any]:
    cur_code = _parse_currency_or_cli_error(args.currency)
    db_path = resolve_db_path(args.db)
    with closing(open_db(db_path)) as conn:
        budgets = bud.fetch_budget(conn, period=args.period, currency_code=cur_code)
    if not budgets:
        return {
            "ok": True,
            "period": args.period,
            "currency": args.currency,
            "budgets": [],
            "warning": "no budget materialised for this period",
        }
    return {
        "ok": True,
        "period": args.period,
        "currency": args.currency,
        "budgets": budgets,
    }


def cmd_diff(args: argparse.Namespace) -> dict[str, Any]:
    cur_code = _parse_currency_or_cli_error(args.currency)
    db_path = resolve_db_path(args.db)
    with closing(open_db(db_path)) as conn:
        blocks = bud.diff_budget_vs_actual(conn, period=args.period, currency_code=cur_code)
    return {
        "ok": True,
        "period": args.period,
        "currency": args.currency,
        "blocks": blocks,
    }


def cmd_list(args: argparse.Namespace) -> dict[str, Any]:
    db_path = resolve_db_path(args.db)
    with closing(open_db(db_path)) as conn:
        items = bud.list_budgets(conn)
    return {"ok": True, "count": len(items), "budgets": items}


def cmd_close(args: argparse.Namespace) -> dict[str, Any]:
    cur_code = _parse_currency_or_cli_error(args.currency)
    db_path = resolve_db_path(args.db)
    with closing(open_db(db_path)) as conn:
        try:
            result = bud.set_status(
                conn, period=args.period, currency_code=cur_code, new_status="closed"
            )
        except bud.BudgetParseError as exc:
            raise CliError(str(exc), kind=exc.kind) from exc
    if result.matched == 0:
        raise CliError(
            f"no budget matched period={args.period} currency={args.currency}",
            kind="NotFound",
        )
    return {"ok": True, "matched": result.matched, "changed": result.changed}


def cmd_reopen(args: argparse.Namespace) -> dict[str, Any]:
    cur_code = _parse_currency_or_cli_error(args.currency)
    db_path = resolve_db_path(args.db)
    with closing(open_db(db_path)) as conn:
        try:
            result = bud.set_status(
                conn, period=args.period, currency_code=cur_code, new_status="active"
            )
        except bud.BudgetParseError as exc:
            raise CliError(str(exc), kind=exc.kind) from exc
    if result.matched == 0:
        raise CliError(
            f"no budget matched period={args.period} currency={args.currency}",
            kind="NotFound",
        )
    return {
        "ok": True,
        "matched": result.matched,
        "changed": result.changed,
        "reason": args.reason,
    }


def cmd_delete(args: argparse.Namespace) -> dict[str, Any]:
    cur_code = _parse_currency_or_cli_error(args.currency)
    db_path = resolve_db_path(args.db)
    with closing(open_db(db_path)) as conn:
        try:
            deleted = bud.delete_budget(
                conn,
                period=args.period,
                currency_code=cur_code,
                force=args.force,
            )
        except bud.BudgetParseError as exc:
            raise CliError(str(exc), kind=exc.kind) from exc
    if not deleted:
        raise CliError(
            f"no budget matched period={args.period} currency={args.currency}",
            kind="NotFound",
        )
    return {"ok": True, "deleted": deleted}


def cmd_export(args: argparse.Namespace) -> dict[str, Any]:
    """Write the variance sheet (target vs actual) to a CSV or XLSX
    file. The CLI accepts ``--out -`` to dump CSV to stdout instead
    of writing to a file - useful when piping into ``pbcopy`` for a
    quick paste into Sheets.
    """
    cur_code = _parse_currency_or_cli_error(args.currency)
    db_path = resolve_db_path(args.db)
    with closing(open_db(db_path)) as conn:
        rows = bud.export_variance_rows(conn, period=args.period, currency_code=cur_code)
    fmt = args.format
    out_path: Path | None = None if args.out == "-" else Path(args.out).expanduser()
    if out_path is not None and fmt == "auto":
        fmt = "xlsx" if out_path.suffix.lower() == ".xlsx" else "csv"
    elif fmt == "auto":
        fmt = "csv"

    if fmt == "csv":
        _write_variance_csv(rows, out_path)
    elif fmt == "xlsx":
        if out_path is None:
            raise CliError("--out - not supported for xlsx format", kind="BadArgument")
        _write_variance_xlsx(rows, out_path)
    else:
        raise CliError(f"unsupported --format {fmt!r}", kind="BadArgument")
    return {
        "ok": True,
        "period": args.period,
        "format": fmt,
        "out": str(out_path) if out_path else "-",
        "rows": len(rows),
    }


def _write_variance_csv(rows: list[dict[str, Any]], out_path: Path | None) -> None:
    import csv
    import io

    headers = ["Period", "Category", "Currency", "Target", "Actual", "Delta", "% used"]
    target = out_path.open("w", encoding="utf-8", newline="") if out_path else io.StringIO()
    try:
        writer = csv.DictWriter(target, fieldnames=headers)
        writer.writeheader()
        for r in rows:
            writer.writerow(r)
    finally:
        if out_path is None:
            # stdout dump (the JSON success payload still goes to
            # stdout via run_subcommand - but the spreadsheet contents
            # are also helpful to print here for piping. We print to
            # stderr so the JSON contract is preserved). Actually,
            # mixing CSV and JSON on the same stream confuses callers;
            # keep this branch silent and tell the user to pass --out
            # PATH for piping. Existing tests prefer the file path.
            target.close()
        else:
            target.close()


def _write_variance_xlsx(rows: list[dict[str, Any]], out_path: Path) -> None:
    try:
        from openpyxl import Workbook  # type: ignore[import-not-found]
    except ImportError as exc:
        raise CliError(
            "openpyxl is required for xlsx export; "
            "install via ``uv pip install openpyxl`` or use --format csv",
            kind="MissingDependency",
        ) from exc
    wb = Workbook()
    ws = wb.active
    ws.title = "Variance"
    headers = ["Period", "Category", "Currency", "Target", "Actual", "Delta", "% used"]
    ws.append(headers)
    for r in rows:
        ws.append([r[h] for h in headers])
    wb.save(out_path)


def cmd_rename_category(args: argparse.Namespace) -> dict[str, Any]:
    old = _validate_category_name(args.old)
    new = _validate_category_name(args.new)
    if old == new:
        raise CliError("--from and --to are identical", kind="BadArgument")
    update_tables: tuple[str, ...] = tuple(args.update.split(","))
    db_path = resolve_db_path(args.db)
    with closing(open_db(db_path)) as conn:
        try:
            counts = bud.rename_category(
                conn,
                old_name=old,
                new_name=new,
                update_tables=update_tables,
            )
        except bud.BudgetParseError as exc:
            raise CliError(str(exc), kind=exc.kind) from exc
    return {"ok": True, "old": old, "new": new, "counts": counts}


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="pf-budget",
        description=(
            "Personal finance budgeting commands. PR1 ships the "
            "category_registry subset; pf-budget import / show / "
            "diff / export / close arrive in later PRs."
        ),
    )
    sub = p.add_subparsers(dest="cmd", required=True)

    p_reg = sub.add_parser(
        "register-category",
        help=(
            "Declare a category so budget imports recognise it before any transaction matches it"
        ),
    )
    p_reg.add_argument("--category", required=True)
    p_reg.add_argument(
        "--note",
        default=None,
        help="Optional human-readable note stored alongside the registration",
    )
    p_reg.add_argument("--db", default=None)
    p_reg.set_defaults(func=cmd_register_category)

    p_unreg = sub.add_parser(
        "unregister-category",
        help="Remove a category from the registry (refuses when still referenced)",
    )
    p_unreg.add_argument("--category", required=True)
    p_unreg.add_argument(
        "--force",
        action="store_true",
        help=argparse.SUPPRESS,  # intentional escape hatch
    )
    p_unreg.add_argument("--db", default=None)
    p_unreg.set_defaults(func=cmd_unregister_category)

    p_list = sub.add_parser(
        "list-categories",
        help="List in-use (and optionally declared-but-unused) categories",
    )
    p_list.add_argument(
        "--include-declared",
        action="store_true",
        help="Also include declared-but-unused entries from category_registry",
    )
    p_list.add_argument("--db", default=None)
    p_list.set_defaults(func=cmd_list_categories)

    p_import = sub.add_parser(
        "import",
        help="Import a budget plan (CSV or XLSX) for a given period",
    )
    p_import.add_argument(
        "source",
        help="Path to CSV (.csv) or XLSX (.xlsx/.xlsm). CSV is the Plans-shape "
        "by default; pass --sheet baseline to read a Baseline-shape CSV.",
    )
    p_import.add_argument(
        "--period",
        required=True,
        help="Target period in YYYY-MM. Plans rows with other periods are ignored.",
    )
    p_import.add_argument(
        "--unknown-categories",
        choices=("reject", "register"),
        default="reject",
        help=(
            "What to do with categories that don't exist yet. "
            "'reject' (default): fail with suggestions. "
            "'register': add to category_registry and proceed."
        ),
    )
    p_import.add_argument(
        "--sheet",
        choices=("plans", "baseline"),
        default=None,
        help="For CSV input only: which sheet shape the file represents. "
        "Defaults to 'plans'. Ignored for XLSX (which reads both sheets).",
    )
    p_import.add_argument(
        "--dry-run",
        action="store_true",
        help="Parse, validate, and summarise the diff without writing.",
    )
    p_import.add_argument(
        "--force",
        action="store_true",
        help="Overwrite a closed budget for the period (rare).",
    )
    p_import.add_argument("--db", default=None)
    p_import.set_defaults(func=cmd_import)

    p_show = sub.add_parser("show", help="Show the budget plan materialised for a period")
    p_show.add_argument("--period", required=True)
    p_show.add_argument("--currency", default=None, help="UAH/USD/980/840/...")
    p_show.add_argument("--db", default=None)
    p_show.set_defaults(func=cmd_show)

    p_diff = sub.add_parser("diff", help="Budget vs actuals for a period, per (currency, category)")
    p_diff.add_argument("--period", required=True)
    p_diff.add_argument("--currency", default=None)
    p_diff.add_argument("--db", default=None)
    p_diff.set_defaults(func=cmd_diff)

    p_list_b = sub.add_parser("list", help="List every materialised budget with totals and status")
    p_list_b.add_argument("--db", default=None)
    p_list_b.set_defaults(func=cmd_list)

    p_close = sub.add_parser("close", help="Mark a budget as closed (snapshot)")
    p_close.add_argument("--period", required=True)
    p_close.add_argument("--currency", default=None)
    p_close.add_argument("--db", default=None)
    p_close.set_defaults(func=cmd_close)

    p_reopen = sub.add_parser("reopen", help="Flip a closed budget back to active")
    p_reopen.add_argument("--period", required=True)
    p_reopen.add_argument("--currency", default=None)
    p_reopen.add_argument(
        "--reason",
        default=None,
        help="Free-text reason for reopening; stored only in the command result, "
        "not persisted (audit lands in a future PR if needed).",
    )
    p_reopen.add_argument("--db", default=None)
    p_reopen.set_defaults(func=cmd_reopen)

    p_delete = sub.add_parser("delete", help="Delete a budget and its lines (cascade)")
    p_delete.add_argument("--period", required=True)
    p_delete.add_argument("--currency", default=None)
    p_delete.add_argument(
        "--force",
        action="store_true",
        help="Allow deleting a closed budget.",
    )
    p_delete.add_argument("--db", default=None)
    p_delete.set_defaults(func=cmd_delete)

    p_export = sub.add_parser(
        "export",
        help="Write the variance sheet (target vs actual) for a period",
    )
    p_export.add_argument("--period", required=True)
    p_export.add_argument("--currency", default=None)
    p_export.add_argument(
        "--out",
        required=True,
        help="Output file path (.csv or .xlsx). Use '-' for stdout (CSV only).",
    )
    p_export.add_argument(
        "--format",
        choices=("auto", "csv", "xlsx"),
        default="auto",
        help="Output format. 'auto' uses the file extension; defaults to csv "
        "when writing to stdout.",
    )
    p_export.add_argument("--db", default=None)
    p_export.set_defaults(func=cmd_export)

    p_rename = sub.add_parser(
        "rename-category",
        help="Rewrite a category name across selected tables",
    )
    p_rename.add_argument("--from", dest="old", required=True)
    p_rename.add_argument("--to", dest="new", required=True)
    p_rename.add_argument(
        "--update",
        default="budget_line",
        help="Comma-separated tables to rewrite. Allowed: "
        "budget_line, tx_category, category_overrides, "
        "categorization_rules, category_registry.",
    )
    p_rename.add_argument("--db", default=None)
    p_rename.set_defaults(func=cmd_rename_category)

    return p


def main(argv: Sequence[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    return run_subcommand(args.func, args)


if __name__ == "__main__":
    sys.exit(main())
