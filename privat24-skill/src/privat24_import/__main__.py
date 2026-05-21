"""CLI entry for the Privat24 import skill.

Usage::

    uv run privat24-import import <file.xlsx> [--no-archive] [--data-dir DIR]
    uv run privat24-import import-inbox [--no-archive] [--data-dir DIR]

Both commands write to the shared SQLite store at
``$MONOBANK_MCP_DATA_DIR/data.db`` (or ``~/finances/data.db`` by default).
After a successful import the source file is moved to
``$DATA_DIR/archive/YYYY-MM-DD/`` so the inbox stays clean.

The CLI is intentionally thin - the heavy lifting lives in
``parsers.web_xlsx`` (decoding) and ``core.store`` (persistence). SKILL.md
in this plugin's ``skills/privat24-import/`` directory tells Claude how
to invoke this from inside a conversation.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Sequence

from .core import dedup as dedup_mod
from .core import store as store_mod
from .parsers import detect as detect_mod
from .parsers import web_xlsx as web_xlsx_mod


def _resolve_data_dir(arg: str | None) -> Path:
    if arg:
        return Path(arg).expanduser()
    env = os.environ.get("MONOBANK_MCP_DATA_DIR")
    if env:
        return Path(env).expanduser()
    return Path.home() / "finances"


def _archive_file(src: Path, data_dir: Path) -> Path:
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    dst_dir = data_dir / "archive" / today
    dst_dir.mkdir(parents=True, exist_ok=True)
    dst = dst_dir / src.name
    # Don't clobber an earlier archived copy with the same name.
    if dst.exists():
        stem, suffix = dst.stem, dst.suffix
        i = 1
        while (dst_dir / f"{stem}.{i}{suffix}").exists():
            i += 1
        dst = dst_dir / f"{stem}.{i}{suffix}"
    shutil.move(str(src), str(dst))
    return dst


def import_one(
    file: Path,
    *,
    data_dir: Path,
    do_archive: bool,
) -> dict:
    """Import a single file. Returns a JSON-serialisable result dict.

    Result shape::

        {"file": "...", "status": "imported" | "skipped" | "unsupported" | "error",
         "rows_inserted": int, "rows_skipped": int, "import_run_id": int | None,
         "error": str | None, "archived_to": str | None}

    Status semantics:
      - ``imported``: parser ran, rows landed (possibly 0 if file is empty).
      - ``skipped``:  same byte sequence already in ``privat_import_runs``.
      - ``unsupported``: ``detect`` couldn't classify the file.
      - ``error``: parser or store raised; ``error`` carries the message.
    """
    sha = dedup_mod.file_sha256(str(file))
    conn = store_mod.open_db(data_dir / "data.db")
    try:
        prior = store_mod.already_imported(conn, sha)
        if prior is not None:
            return {
                "file": str(file),
                "status": "skipped",
                "rows_inserted": 0,
                "rows_skipped": 0,
                "import_run_id": prior,
                "error": None,
                "archived_to": None,
            }
        det = detect_mod.detect(file)
        if det.fmt is detect_mod.Format.UNKNOWN:
            return {
                "file": str(file),
                "status": "unsupported",
                "rows_inserted": 0,
                "rows_skipped": 0,
                "import_run_id": None,
                "error": det.reason,
                "archived_to": None,
            }
        run_id = store_mod.start_import_run(
            conn,
            source=det.fmt.value,
            file_path=str(file),
            file_sha256=sha,
        )
        try:
            outcome = _do_import(conn, file, det.fmt, run_id)
            store_mod.finish_import_run(
                conn,
                run_id,
                rows_inserted=outcome.rows_inserted,
                rows_skipped=outcome.rows_skipped,
            )
        except Exception as exc:  # noqa: BLE001 - we want the message
            store_mod.finish_import_run(
                conn,
                run_id,
                rows_inserted=0,
                rows_skipped=0,
                error=str(exc),
            )
            return {
                "file": str(file),
                "status": "error",
                "rows_inserted": 0,
                "rows_skipped": 0,
                "import_run_id": run_id,
                "error": str(exc),
                "archived_to": None,
            }
        archived = None
        if do_archive:
            archived = str(_archive_file(file, data_dir))
        return {
            "file": str(file),
            "status": "imported",
            "rows_inserted": outcome.rows_inserted,
            "rows_skipped": outcome.rows_skipped,
            "import_run_id": run_id,
            "error": None,
            "archived_to": archived,
        }
    finally:
        conn.close()


def _do_import(
    conn: sqlite3.Connection,
    file: Path,
    fmt: detect_mod.Format,
    run_id: int,
) -> store_mod.InsertOutcome:
    if fmt is not detect_mod.Format.WEB_XLSX:
        # Future formats route here. For now keep this branch tight to
        # avoid silent "did nothing" paths.
        raise NotImplementedError(f"no importer for {fmt.value}")
    parsed = web_xlsx_mod.parse(file)
    store_mod.upsert_account(
        conn,
        account_id=parsed.account_id,
        iban=None,
        account_type=None,
        currency_code=parsed.account_currency_code,
        masked_pan=parsed.masked_pan,
    )
    keys = [
        {
            "ts": r.ts,
            "amount_minor": r.amount_minor,
            "description": r.description,
            "account_id": parsed.account_id,
        }
        for r in parsed.rows
    ]
    ids = dedup_mod.assign_ids(keys)
    txs = [
        store_mod.Tx(
            id=tx_id,
            account_id=parsed.account_id,
            ts=r.ts,
            amount_minor=r.amount_minor,
            currency_code=r.currency_code,
            op_amount_minor=r.op_amount_minor,
            op_currency_code=r.op_currency_code,
            mcc=None,
            description=r.description,
            counterparty=None,
            balance_minor=r.balance_minor,
            raw=r.raw,
        )
        for tx_id, r in zip(ids, parsed.rows)
    ]
    return store_mod.insert_transactions(conn, run_id=run_id, txs=txs)


def cmd_import(args: argparse.Namespace) -> int:
    data_dir = _resolve_data_dir(args.data_dir)
    file = Path(args.file).expanduser()
    if not file.exists():
        _emit_error(f"file not found: {file}")
        return 1
    result = import_one(file, data_dir=data_dir, do_archive=not args.no_archive)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["status"] in {"imported", "skipped"} else 1


def cmd_import_inbox(args: argparse.Namespace) -> int:
    data_dir = _resolve_data_dir(args.data_dir)
    inbox = data_dir / "inbox"
    if not inbox.exists():
        _emit_error(f"inbox dir not found: {inbox}")
        return 1
    files = sorted(inbox.glob("privat*.xlsx")) + sorted(inbox.glob("*.xlsx"))
    # de-dup paths while preserving order
    seen: set[Path] = set()
    files = [p for p in files if not (p in seen or seen.add(p))]
    if not files:
        print(json.dumps({"status": "empty", "inbox": str(inbox)}, indent=2))
        return 0
    results = []
    any_error = False
    for f in files:
        r = import_one(f, data_dir=data_dir, do_archive=not args.no_archive)
        results.append(r)
        if r["status"] not in {"imported", "skipped"}:
            any_error = True
    print(json.dumps(results, ensure_ascii=False, indent=2))
    return 1 if any_error else 0


def _emit_error(msg: str) -> None:
    print(
        json.dumps({"status": "error", "error": msg}, ensure_ascii=False),
        file=sys.stderr,
    )


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="privat24-import",
        description="Import Privat24 statement exports into ~/finances/data.db",
    )
    sub = p.add_subparsers(dest="cmd", required=True)

    p_imp = sub.add_parser("import", help="Import a single XLSX file")
    p_imp.add_argument("file", help="Path to the XLSX export")
    p_imp.add_argument(
        "--no-archive",
        action="store_true",
        help="Don't move the file to archive/ after import",
    )
    p_imp.add_argument(
        "--data-dir",
        default=None,
        help="Override data directory (default: $MONOBANK_MCP_DATA_DIR or ~/finances)",
    )
    p_imp.set_defaults(func=cmd_import)

    p_inbox = sub.add_parser(
        "import-inbox",
        help="Import every XLSX in $DATA_DIR/inbox/",
    )
    p_inbox.add_argument("--no-archive", action="store_true")
    p_inbox.add_argument("--data-dir", default=None)
    p_inbox.set_defaults(func=cmd_import_inbox)

    return p


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
