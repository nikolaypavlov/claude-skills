"""``pf-cli`` entry point - a thin wrapper around the read queries for
ad-hoc inspection from a terminal. Useful when debugging without
spawning a full MCP session."""

from __future__ import annotations

import argparse
import json
import sys

from . import queries, store
from .view import discover_sources


def _cmd_accounts(_: argparse.Namespace) -> int:
    conn = store.open_db()
    try:
        rows = queries.list_accounts(conn)
    finally:
        conn.close()
    print(json.dumps([dict(r) for r in rows], indent=2, ensure_ascii=False))
    return 0


def _cmd_sources(_: argparse.Namespace) -> int:
    conn = store.open_db()
    try:
        sources = discover_sources(conn)
        version = store.schema_version(conn)
    finally:
        conn.close()
    print(
        json.dumps(
            {
                "detected_banks": list(sources.tx_banks),
                "detected_account_banks": list(sources.account_banks),
                "pf_schema_version": version,
            },
            indent=2,
        )
    )
    return 0


def _cmd_transactions(args: argparse.Namespace) -> int:
    conn = store.open_db()
    try:
        rows = queries.get_transactions(
            conn,
            from_ts=args.from_ts,
            to_ts=args.to_ts,
            account_id=args.account_id,
            bank=args.bank,
            limit=args.limit,
        )
    finally:
        conn.close()
    print(json.dumps([dict(r) for r in rows], indent=2, ensure_ascii=False))
    return 0


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
    args = build_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
