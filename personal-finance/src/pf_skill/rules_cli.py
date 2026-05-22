"""``pf-rules`` CLI entry: manage categorization rules and overrides.

Subcommands::

    pf-rules add --match-field FIELD --pattern P --category C
                 [--priority N] [--source S] [--apply]
    pf-rules apply --rule-id N [--dry-run]
    pf-rules set-category --tx-id ID --category C [--note T]
    pf-rules set-override --tx-id ID --category C [--note T]
    pf-rules reload
    pf-rules list [--enabled-only] [--source S]

Every mutating subcommand runs inside an explicit BEGIN/COMMIT so a
crash mid-call leaves the store consistent. ``add`` is preview-by-
default: it inserts the rule row but does NOT retroactively backfill
``tx_category`` unless ``--apply`` is set. SKILL.md tells Claude to
show the preview to the user first and only call ``apply`` on yes.
"""

from __future__ import annotations

import argparse
import sys
import time
from collections.abc import Sequence
from contextlib import closing
from typing import Any

from .common.categorizer import (
    DEFAULT_PRIORITY_FOR_FIELD,
    apply_rule_by_id,
    preview_rule,
)
from .common.cli import (
    CliError,
    resolve_db_path,
    run_subcommand,
)
from .common.rules import VALID_MATCH_FIELDS, load_all_rules
from .common.store import open_db


def cmd_add(args: argparse.Namespace) -> dict[str, Any]:
    """Insert a rule into categorization_rules; preview unless --apply.

    Returns the new rule id, the preview shape (would_affect_count +
    sample), and `applied` showing how many rows were retroactively
    categorized (0 unless --apply was set).
    """
    if args.match_field not in VALID_MATCH_FIELDS:
        raise CliError(
            f"--match-field must be one of {list(VALID_MATCH_FIELDS)}, got {args.match_field!r}"
        )
    if not args.pattern:
        raise CliError("--pattern must be non-empty")
    if not args.category:
        raise CliError("--category must be non-empty")
    priority = (
        int(args.priority)
        if args.priority is not None
        else DEFAULT_PRIORITY_FOR_FIELD[args.match_field]
    )
    now_ts = int(time.time())
    db_path = resolve_db_path(args.db)
    with closing(open_db(db_path)) as conn:
        conn.execute("BEGIN")
        try:
            cur = conn.execute(
                "INSERT INTO categorization_rules "
                "(priority, match_field, pattern, category, enabled, created_at, source) "
                "VALUES (?, ?, ?, ?, 1, ?, ?)",
                (
                    priority,
                    args.match_field,
                    args.pattern,
                    args.category,
                    now_ts,
                    args.source,
                ),
            )
            rule_id = int(cur.lastrowid or 0)
            conn.commit()
        except Exception:
            conn.rollback()
            raise

        preview = preview_rule(
            conn,
            match_field=args.match_field,
            pattern=args.pattern,
            category=args.category,
            limit_sample=5,
        )

        applied = 0
        if args.apply and preview["would_affect_count"] > 0:
            applied_result = apply_rule_by_id(conn, rule_id=rule_id, dry_run=False, now=now_ts)
            applied = int(applied_result["applied"])

    return {
        "ok": True,
        "rule_id": rule_id,
        "priority": priority,
        "match_field": args.match_field,
        "pattern": args.pattern,
        "category": args.category,
        "source": args.source,
        "would_affect_count": preview["would_affect_count"],
        "sample": preview["sample"],
        "applied": applied,
    }


def cmd_apply(args: argparse.Namespace) -> dict[str, Any]:
    db_path = resolve_db_path(args.db)
    try:
        with closing(open_db(db_path)) as conn:
            result = apply_rule_by_id(conn, rule_id=int(args.rule_id), dry_run=bool(args.dry_run))
    except ValueError as exc:
        raise CliError(str(exc), kind="ValueError") from exc
    return {"ok": True, **result}


def cmd_set_category(args: argparse.Namespace) -> dict[str, Any]:
    if not args.tx_id or not args.category:
        raise CliError("--tx-id and --category are both required")
    now_ts = int(time.time())
    db_path = resolve_db_path(args.db)
    with closing(open_db(db_path)) as conn:
        conn.execute("BEGIN")
        try:
            conn.execute(
                "INSERT OR REPLACE INTO tx_category "
                "(tx_id, category, rule_id, set_at, set_by) "
                "VALUES (?, ?, NULL, ?, 'manual')",
                (args.tx_id, args.category, now_ts),
            )
            conn.commit()
        except Exception:
            conn.rollback()
            raise
    return {
        "ok": True,
        "tx_id": args.tx_id,
        "category": args.category,
        "set_at": now_ts,
        "set_by": "manual",
    }


def cmd_set_override(args: argparse.Namespace) -> dict[str, Any]:
    if not args.tx_id or not args.category:
        raise CliError("--tx-id and --category are both required")
    now_ts = int(time.time())
    db_path = resolve_db_path(args.db)
    with closing(open_db(db_path)) as conn:
        conn.execute("BEGIN")
        try:
            conn.execute(
                "INSERT OR REPLACE INTO category_overrides "
                "(tx_id, category, note, set_at) VALUES (?, ?, ?, ?)",
                (args.tx_id, args.category, args.note, now_ts),
            )
            conn.commit()
        except Exception:
            conn.rollback()
            raise
    return {
        "ok": True,
        "tx_id": args.tx_id,
        "category": args.category,
        "note": args.note,
        "set_at": now_ts,
    }


def cmd_reload(_args: argparse.Namespace) -> dict[str, Any]:
    """No-op today: rules.load_all_rules reads every source on every
    invocation. The subcommand exists so SKILL.md can pretend to have
    a refresh action without lying about the contract - we just count
    the active rules so the user sees a real number back."""
    db_path = resolve_db_path(_args.db)
    with closing(open_db(db_path)) as conn:
        rules = load_all_rules(conn, data_dir=db_path.parent)
    return {
        "ok": True,
        "rules_count": len(rules),
        "note": "rules reload on every invocation; nothing cached",
    }


def cmd_list(args: argparse.Namespace) -> dict[str, Any]:
    db_path = resolve_db_path(args.db)
    with closing(open_db(db_path)) as conn:
        rules = load_all_rules(conn, data_dir=db_path.parent)
    if args.source:
        rules = [r for r in rules if r.source == args.source]
    if args.enabled_only:
        rules = [r for r in rules if r.enabled]
    return {
        "ok": True,
        "count": len(rules),
        "rules": [
            {
                "rule_id": r.rule_id,
                "priority": r.priority,
                "match_field": r.match_field,
                "pattern": r.pattern,
                "category": r.category,
                "source": r.source,
                "enabled": r.enabled,
            }
            for r in rules
        ],
    }


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="pf-rules",
        description="Manage categorization rules and per-tx overrides",
    )
    sub = p.add_subparsers(dest="cmd", required=True)

    p_add = sub.add_parser(
        "add",
        help="Insert a rule; preview by default, --apply for retroactive backfill",
    )
    p_add.add_argument(
        "--match-field",
        required=True,
        help=f"One of {list(VALID_MATCH_FIELDS)}",
    )
    p_add.add_argument("--pattern", required=True)
    p_add.add_argument("--category", required=True)
    p_add.add_argument("--priority", type=int, default=None)
    p_add.add_argument("--source", default="user")
    p_add.add_argument(
        "--apply",
        action="store_true",
        help="Retroactively apply the rule in the same call (skip the preview-then-apply step)",
    )
    p_add.add_argument("--db", default=None)
    p_add.set_defaults(func=cmd_add)

    p_apply = sub.add_parser("apply", help="Retroactively apply a rule by id")
    p_apply.add_argument("--rule-id", required=True, type=int)
    p_apply.add_argument(
        "--dry-run",
        action="store_true",
        help="Report what would change without writing",
    )
    p_apply.add_argument("--db", default=None)
    p_apply.set_defaults(func=cmd_apply)

    p_set = sub.add_parser("set-category", help="Pin a single tx to a category (tx_category)")
    p_set.add_argument("--tx-id", required=True)
    p_set.add_argument("--category", required=True)
    p_set.add_argument("--note", default=None, help="Stored only for set-override; ignored here")
    p_set.add_argument("--db", default=None)
    p_set.set_defaults(func=cmd_set_category)

    p_over = sub.add_parser(
        "set-override",
        help="Pin a single tx through category_overrides (wins over rules)",
    )
    p_over.add_argument("--tx-id", required=True)
    p_over.add_argument("--category", required=True)
    p_over.add_argument("--note", default=None)
    p_over.add_argument("--db", default=None)
    p_over.set_defaults(func=cmd_set_override)

    p_reload = sub.add_parser(
        "reload",
        help="Refresh the rule view (no-op today; rules reload at every call)",
    )
    p_reload.add_argument("--db", default=None)
    p_reload.set_defaults(func=cmd_reload)

    p_list = sub.add_parser("list", help="List rules merged from every source")
    p_list.add_argument(
        "--enabled-only",
        action="store_true",
        help="Drop disabled DB rules from the output",
    )
    p_list.add_argument(
        "--source",
        default=None,
        help="Filter by source: seed-mcc / seed-description / local-counterparty / db",
    )
    p_list.add_argument("--db", default=None)
    p_list.set_defaults(func=cmd_list)

    return p


def main(argv: Sequence[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    return run_subcommand(args.func, args)


if __name__ == "__main__":
    sys.exit(main())
