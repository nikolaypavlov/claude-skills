"""``pf-query`` CLI entry: read-only queries over the shared store.

Subcommands::

    pf-query accounts
    pf-query categories
    pf-query list --from <ts> --to <ts> [filters]
    pf-query summarize --from <ts> --to <ts> --group-by <key> [filters]
    pf-query summarize-uncategorized [--from <ts>] [--to <ts>] [--group-by <key>] [filters]
    pf-query find --query <text> [--limit N]

``--from`` / ``--to`` accept either unix seconds or an ISO 8601 string
(see ``common.cli.parse_time_arg``). Every subcommand prints a JSON
result to stdout and exits 0; bad arguments or DB errors print the
structured ``{"ok": false, ...}`` payload to stderr and exit 1.

The CLI is intentionally a thin shell around ``pf_skill.common.queries``.
All SQL lives in the common module so categorize/rules/report can reuse
the same shapes without re-implementing UNION ALL discovery.
"""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence
from contextlib import closing
from typing import Any

from .common import queries as q
from .common.cli import (
    CliError,
    parse_time_arg,
    resolve_db_path,
    run_subcommand,
)
from .common.currencies import parse_currency_arg
from .common.store import open_db
from .common.view import discover_sources


def _parse_currency_or_cli_error(value: str | None) -> int | None:
    """Wrap ``parse_currency_arg`` so unknown / malformed inputs land
    through the JSON-error contract (exit 1) rather than as uncaught
    ValueError (exit 2)."""
    if value is None:
        return None
    try:
        return parse_currency_arg(value)
    except ValueError as exc:
        raise CliError(str(exc), kind="ValueError") from exc


def cmd_accounts(args: argparse.Namespace) -> dict[str, Any]:
    db_path = resolve_db_path(args.db)
    with closing(open_db(db_path)) as conn:
        sources = discover_sources(conn)
        accounts = q.list_accounts(conn, sources=sources)
    payload: dict[str, Any] = {
        "ok": True,
        "detected_banks": list(sources.account_banks),
        "accounts": accounts,
    }
    if not sources.has_any_tx():
        payload["warning"] = (
            "no transaction sources detected - install at least one ingest "
            "plugin (monobank-mcp or privat24-skill)"
        )
    return payload


def cmd_list(args: argparse.Namespace) -> dict[str, Any]:
    db_path = resolve_db_path(args.db)
    from_ts = parse_time_arg(args.from_, flag="--from")
    to_ts = parse_time_arg(args.to, flag="--to")
    if from_ts >= to_ts:
        raise CliError(f"--from ({from_ts}) must be strictly less than --to ({to_ts})")
    currency_code = _parse_currency_or_cli_error(args.currency)
    with closing(open_db(db_path)) as conn:
        rows = q.get_transactions(
            conn,
            from_ts=from_ts,
            to_ts=to_ts,
            account_id=args.account,
            bank=args.bank,
            category=args.category,
            currency_code=currency_code,
            limit=args.limit,
            offset=args.offset,
        )
    return {
        "ok": True,
        "from_ts": from_ts,
        "to_ts": to_ts,
        "count": len(rows),
        "transactions": rows,
    }


def cmd_summarize(args: argparse.Namespace) -> dict[str, Any]:
    db_path = resolve_db_path(args.db)
    from_ts = parse_time_arg(args.from_, flag="--from")
    to_ts = parse_time_arg(args.to, flag="--to")
    if from_ts >= to_ts:
        raise CliError(f"--from ({from_ts}) must be strictly less than --to ({to_ts})")
    currency_code = _parse_currency_or_cli_error(args.currency)
    try:
        with closing(open_db(db_path)) as conn:
            buckets = q.summarize_spending(
                conn,
                from_ts=from_ts,
                to_ts=to_ts,
                group_by=args.group_by,
                account_id=args.account,
                bank=args.bank,
                currency_code=currency_code,
            )
    except ValueError as exc:
        # The only ValueError summarize_spending raises is "unsupported
        # group_by"; re-raise as CliError so the unified JSON-error
        # contract (exit 1, stderr payload) is preserved instead of
        # bubbling up as an uncaught exception (exit 2).
        raise CliError(f"--group-by: {exc}", kind="ValueError") from exc
    return {
        "ok": True,
        "from_ts": from_ts,
        "to_ts": to_ts,
        "group_by": args.group_by,
        "buckets": buckets,
    }


def cmd_categories(args: argparse.Namespace) -> dict[str, Any]:
    db_path = resolve_db_path(args.db)
    with closing(open_db(db_path)) as conn:
        cats = q.list_categories(conn, include_declared=args.include_declared)
    return {
        "ok": True,
        "count": len(cats),
        "categories": cats,
    }


def cmd_summarize_uncategorized(args: argparse.Namespace) -> dict[str, Any]:
    db_path = resolve_db_path(args.db)
    from_ts = parse_time_arg(args.from_, flag="--from") if args.from_ else None
    to_ts = parse_time_arg(args.to, flag="--to") if args.to else None
    if from_ts is not None and to_ts is not None and from_ts >= to_ts:
        raise CliError(f"--from ({from_ts}) must be strictly less than --to ({to_ts})")
    currency_code = _parse_currency_or_cli_error(args.currency)
    try:
        with closing(open_db(db_path)) as conn:
            buckets = q.summarize_uncategorized(
                conn,
                from_ts=from_ts,
                to_ts=to_ts,
                group_by=args.group_by,
                account_id=args.account,
                bank=args.bank,
                currency_code=currency_code,
            )
    except ValueError as exc:
        raise CliError(f"--group-by: {exc}", kind="ValueError") from exc
    return {
        "ok": True,
        "from_ts": from_ts,
        "to_ts": to_ts,
        "group_by": args.group_by,
        "count": len(buckets),
        "buckets": buckets,
    }


def cmd_find(args: argparse.Namespace) -> dict[str, Any]:
    db_path = resolve_db_path(args.db)
    text = (args.query or "").strip()
    if not text:
        raise CliError("--query must be non-empty")
    with closing(open_db(db_path)) as conn:
        rows = q.find_transactions(conn, query=text, limit=args.limit)
    return {
        "ok": True,
        "query": text,
        "count": len(rows),
        "transactions": rows,
    }


def _add_common_filters(parser: argparse.ArgumentParser) -> None:
    """Filters shared by ``list`` and ``summarize`` so SKILL.md callers
    can swap subcommands without rewriting the flag list."""
    parser.add_argument("--account", default=None, help="Filter by account_id")
    parser.add_argument("--bank", default=None, help="Filter by bank prefix (e.g. mono, privat)")
    parser.add_argument(
        "--currency",
        default=None,
        help="Filter by currency: alpha-3 (UAH) or ISO numeric (980)",
    )
    parser.add_argument(
        "--db",
        default=None,
        help="Override DB path (default: $MONOBANK_MCP_DATA_DIR or ~/finances/data.db)",
    )


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="pf-query",
        description="Read-only queries over the shared personal-finance store",
    )
    sub = p.add_subparsers(dest="cmd", required=True)

    p_acc = sub.add_parser("accounts", help="List accounts across detected banks")
    p_acc.add_argument("--db", default=None)
    p_acc.set_defaults(func=cmd_accounts)

    p_cats = sub.add_parser(
        "categories",
        help="List every category currently assigned to a transaction, with tx counts",
    )
    p_cats.add_argument(
        "--include-declared",
        action="store_true",
        help=(
            "Also include categories from category_registry that have no "
            "matching transactions yet (tx_count=0, declared=true)"
        ),
    )
    p_cats.add_argument("--db", default=None)
    p_cats.set_defaults(func=cmd_categories)

    p_list = sub.add_parser("list", help="List transactions in a date range")
    p_list.add_argument("--from", dest="from_", required=True, help="Start (unix s or ISO 8601)")
    p_list.add_argument("--to", required=True, help="End exclusive (unix s or ISO 8601)")
    p_list.add_argument("--category", default=None)
    p_list.add_argument("--limit", type=int, default=500)
    p_list.add_argument("--offset", type=int, default=0)
    _add_common_filters(p_list)
    p_list.set_defaults(func=cmd_list)

    p_sum = sub.add_parser("summarize", help="Aggregate spending by a key")
    p_sum.add_argument("--from", dest="from_", required=True, help="Start (unix s or ISO 8601)")
    p_sum.add_argument("--to", required=True, help="End exclusive (unix s or ISO 8601)")
    p_sum.add_argument(
        "--group-by",
        required=True,
        help=f"One of {list(q.valid_group_by_keys())}",
    )
    _add_common_filters(p_sum)
    p_sum.set_defaults(func=cmd_summarize)

    p_unc = sub.add_parser(
        "summarize-uncategorized",
        help="Cluster uncategorized transactions by merchant or MCC",
    )
    p_unc.add_argument(
        "--from",
        dest="from_",
        default=None,
        help="Start (unix s or ISO 8601). Optional - default is all time.",
    )
    p_unc.add_argument(
        "--to",
        default=None,
        help="End exclusive (unix s or ISO 8601). Optional - default is all time.",
    )
    p_unc.add_argument(
        "--group-by",
        default="description",
        help=f"One of {list(q.valid_uncategorized_group_by_keys())} (default: description)",
    )
    _add_common_filters(p_unc)
    p_unc.set_defaults(func=cmd_summarize_uncategorized)

    p_find = sub.add_parser("find", help="Substring search over description and counterparty")
    p_find.add_argument("--query", required=True, help="Substring to search for")
    p_find.add_argument("--limit", type=int, default=100)
    p_find.add_argument("--db", default=None)
    p_find.set_defaults(func=cmd_find)

    return p


def main(argv: Sequence[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    return run_subcommand(args.func, args)


if __name__ == "__main__":
    sys.exit(main())
