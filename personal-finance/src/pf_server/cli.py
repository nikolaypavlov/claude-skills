"""``pf-cli`` entry point - a thin wrapper around the read queries for
ad-hoc inspection from a terminal. Useful when debugging without
spawning a full MCP session.

All subcommands run inside ``_with_db`` which owns the conn lifecycle
and routes any exception through the top-level handler in ``main`` so
the user gets a single-line JSON error instead of a Python traceback
(matching the ``pf-server --probe`` contract).
"""

from __future__ import annotations

import argparse
import contextlib
import json
import sqlite3
import sys
from collections.abc import Callable, Iterator
from typing import Any

from . import queries, store
from .view import discover_sources


@contextlib.contextmanager
def _with_db() -> Iterator[sqlite3.Connection]:
    conn = store.open_db()
    try:
        yield conn
    finally:
        conn.close()


def _emit(obj: Any) -> None:
    print(json.dumps(obj, indent=2, ensure_ascii=False))


def _cmd_accounts(_: argparse.Namespace) -> int:
    with _with_db() as conn:
        _emit([dict(r) for r in queries.list_accounts(conn)])
    return 0


def _cmd_sources(_: argparse.Namespace) -> int:
    with _with_db() as conn:
        sources = discover_sources(conn)
        version = store.schema_version(conn)
    _emit(
        {
            "detected_banks": list(sources.tx_banks),
            "detected_account_banks": list(sources.account_banks),
            "pf_schema_version": version,
        }
    )
    return 0


def _cmd_transactions(args: argparse.Namespace) -> int:
    with _with_db() as conn:
        rows = queries.get_transactions(
            conn,
            from_ts=args.from_ts,
            to_ts=args.to_ts,
            account_id=args.account_id,
            bank=args.bank,
            limit=args.limit,
        )
    _emit([dict(r) for r in rows])
    return 0


# Subcommand handlers must conform to this shape so the dispatcher
# can call them uniformly with the parsed args.
_CmdFn = Callable[[argparse.Namespace], int]


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="pf-cli",
        description="Diagnostic CLI for the personal-finance umbrella server.",
    )
    sub = p.add_subparsers(dest="cmd", required=True)

    sub.add_parser("sources", help="Show detected ingest plugins").set_defaults(
        func=_cmd_sources
    )
    sub.add_parser("accounts", help="List every account across banks").set_defaults(
        func=_cmd_accounts
    )

    p_tx = sub.add_parser("transactions", help="Cross-bank transaction query")
    p_tx.add_argument("--from-ts", type=int, default=None, dest="from_ts")
    p_tx.add_argument("--to-ts", type=int, default=None, dest="to_ts")
    p_tx.add_argument("--account-id", default=None, dest="account_id")
    p_tx.add_argument("--bank", default=None)
    p_tx.add_argument("--limit", type=int, default=50)
    p_tx.set_defaults(func=_cmd_transactions)

    return p


def main(argv: list[str] | None = None) -> int:
    """Entry point. Any exception below this line is converted into a
    single-line JSON error on stderr and a non-zero exit code so the
    output contract matches ``pf-server --probe``.
    """
    args = build_parser().parse_args(argv)
    try:
        return args.func(args)
    except Exception as exc:  # noqa: BLE001 - intentional top-level guard
        print(
            json.dumps(
                {"ok": False, "error": str(exc), "type": type(exc).__name__},
                ensure_ascii=False,
            ),
            file=sys.stderr,
        )
        return 1


if __name__ == "__main__":
    sys.exit(main())
