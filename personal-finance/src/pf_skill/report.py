"""``pf-report`` CLI entry: assemble a JSON report bundle for a period.

Usage::

    pf-report --from <ts> --to <ts>
              [--account <id>] [--bank mono|privat]
              [--comparison previous-period]
              [--db <path>]

Auto-switches between "full" (all transactions inline) and "bucketed"
(monthly_buckets + top_transactions) modes based on the period length;
the threshold lives in ``common.reports.FULL_DUMP_THRESHOLD_DAYS``.

Output contract matches every other ``pf-*`` script - JSON on stdout,
``{"ok": false, ...}`` on stderr + exit 1 for known failures.
"""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence
from contextlib import closing
from typing import Any

from .common.cli import (
    CliError,
    parse_time_arg,
    resolve_db_path,
    run_subcommand,
)
from .common.reports import build_report_bundle
from .common.store import open_db

_VALID_COMPARISONS = ("previous-period",)


def cmd_report(args: argparse.Namespace) -> dict[str, Any]:
    db_path = resolve_db_path(args.db)
    from_ts = parse_time_arg(args.from_, flag="--from")
    to_ts = parse_time_arg(args.to, flag="--to")
    if from_ts >= to_ts:
        raise CliError(
            f"--from ({from_ts}) must be strictly less than --to ({to_ts})"
        )
    if args.comparison is not None and args.comparison not in _VALID_COMPARISONS:
        raise CliError(
            f"--comparison must be one of {list(_VALID_COMPARISONS)}, "
            f"got {args.comparison!r}"
        )
    with closing(open_db(db_path)) as conn:
        return build_report_bundle(
            conn,
            from_ts=from_ts,
            to_ts=to_ts,
            account_id=args.account,
            bank=args.bank,
            comparison=args.comparison,
        )


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="pf-report",
        description=(
            "Assemble a JSON report bundle for a period (full or bucketed mode "
            "depending on period length)."
        ),
    )
    p.add_argument(
        "--from",
        dest="from_",
        required=True,
        help="Period start (unix s or ISO 8601)",
    )
    p.add_argument(
        "--to",
        required=True,
        help="Period end exclusive (unix s or ISO 8601)",
    )
    p.add_argument("--account", default=None, help="Filter to one account_id")
    p.add_argument(
        "--bank", default=None, help="Filter to one bank prefix (mono / privat)"
    )
    p.add_argument(
        "--comparison",
        default=None,
        help=(
            "Add a previous-period comparison. Currently only "
            "'previous-period' (symmetrical window immediately before --from)."
        ),
    )
    p.add_argument(
        "--db",
        default=None,
        help="Override DB path (default: $MONOBANK_MCP_DATA_DIR or ~/finances/data.db)",
    )
    return p


def main(argv: Sequence[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    return run_subcommand(cmd_report, args)


if __name__ == "__main__":
    sys.exit(main())
