"""``pf-budget`` CLI entry: budget management.

PR1 scope (this file):

    pf-budget register-category --category NAME [--note NOTE]
    pf-budget unregister-category --category NAME
    pf-budget list-categories [--include-declared]

Future PRs (per budget-design.md) layer ``import``, ``show``,
``diff``, ``export``, ``close``, ``reopen``, ``rename-category`` on
top of the same parser. Keeping the script registered now means the
plugin venv only needs one re-link as the surface grows.

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
from typing import Any

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

    return p


def main(argv: Sequence[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    return run_subcommand(args.func, args)


if __name__ == "__main__":
    sys.exit(main())
