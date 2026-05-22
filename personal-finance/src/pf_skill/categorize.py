"""``pf-categorize`` CLI entry: run the categorizer pass.

Subcommand-free::

    pf-categorize --scope all
    pf-categorize --scope last-n-days --n 30

Walks the uncategorized transactions in the requested scope, applies
the merged rule set (seed YAML + DB rules), and UPSERTs any
``overrides.local.yaml`` entries into ``category_overrides``. Returns
the same JSON shape on stdout that ``common.categorizer.apply_rules``
produces, with ``ok: true`` prepended for the uniform contract.
"""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence
from contextlib import closing
from typing import Any

from .common.categorizer import VALID_SCOPES, apply_rules
from .common.cli import (
    CliError,
    resolve_db_path,
    run_subcommand,
)
from .common.store import open_db


def cmd_categorize(args: argparse.Namespace) -> dict[str, Any]:
    db_path = resolve_db_path(args.db)
    if args.scope not in VALID_SCOPES:
        raise CliError(f"--scope must be one of {list(VALID_SCOPES)}, got {args.scope!r}")
    if args.scope == "last-n-days" and args.n is None:
        raise CliError("--n is required when --scope=last-n-days")
    if args.scope != "last-n-days" and args.n is not None:
        raise CliError("--n is only valid with --scope=last-n-days")
    with closing(open_db(db_path)) as conn:
        result = apply_rules(
            conn,
            scope=args.scope,
            n_days=args.n if args.n is not None else 0,
            data_dir=db_path.parent,
        )
    return {"ok": True, **result}


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="pf-categorize",
        description=(
            "Run the categorizer over uncategorized transactions and import "
            "overrides.local.yaml into category_overrides."
        ),
    )
    p.add_argument(
        "--scope",
        required=True,
        help=f"Scope of the pass: one of {list(VALID_SCOPES)}",
    )
    p.add_argument(
        "--n",
        type=int,
        default=None,
        help="Day count when --scope=last-n-days (e.g. --n 30)",
    )
    p.add_argument(
        "--db",
        default=None,
        help="Override DB path (default: $MONOBANK_MCP_DATA_DIR or ~/finances/data.db)",
    )
    return p


def main(argv: Sequence[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    return run_subcommand(cmd_categorize, args)


if __name__ == "__main__":
    sys.exit(main())
