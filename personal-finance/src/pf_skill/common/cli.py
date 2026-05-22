"""Shared CLI scaffolding for every ``pf-*`` entry point.

Centralises the JSON output / error contract documented in
``docs/personal-finance-design.md`` §4.3:

- success: ``json.dumps(result)`` to stdout, exit 0
- expected failure (CliError - bad args, IO, DB locked, etc.):
  ``{"ok": false, "error": ..., "type": ...}`` to stderr, exit 1
- uncaught exception: traceback to stderr, exit 2

Every script is expected to wrap its subcommand callables with
``run_subcommand`` so the contract is uniform - Claude (and the
end-to-end CLI tests) can rely on the same parsing rules across
``pf-query``, ``pf-report``, ``pf-categorize``, and ``pf-rules``.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import traceback
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


class CliError(Exception):
    """Raised by subcommands for known / recoverable error conditions.

    Caught by ``run_subcommand`` and emitted as the structured stderr
    payload + exit 1. Use for: bad argument shape, missing file,
    locked / corrupt DB, permission denied. Do NOT use for genuine
    programming bugs - let those crash to traceback + exit 2.
    """

    def __init__(self, message: str, *, kind: str = "ValueError") -> None:
        super().__init__(message)
        self.kind = kind


def run_subcommand(
    func: Callable[[argparse.Namespace], Any],
    args: argparse.Namespace,
) -> int:
    """Invoke ``func(args)``, serialise the return value to stdout,
    handle errors. Returns the integer exit code so callers can
    ``return run_subcommand(...)`` from their ``main``."""
    try:
        result = func(args)
    except CliError as exc:
        _emit_error(str(exc), exc.kind)
        return 1
    except Exception as exc:
        # Print the full traceback to stderr so the user (and Claude)
        # sees the real cause; the JSON-error contract is reserved for
        # CliError. Exit 2 distinguishes "bug" from "expected failure".
        traceback.print_exc(file=sys.stderr)
        _emit_error(f"{type(exc).__name__}: {exc}", "UncaughtException")
        return 2
    print(json.dumps(result, ensure_ascii=False, indent=2, default=_json_default))
    return 0


def _emit_error(message: str, kind: str) -> None:
    print(
        json.dumps(
            {"ok": False, "error": message, "type": kind},
            ensure_ascii=False,
        ),
        file=sys.stderr,
    )


def _json_default(obj: Any) -> Any:
    """Fallback serialiser for objects ``json.dumps`` doesn't know.

    Paths and datetimes are the only ones we expect at the CLI
    boundary. Anything else raises - silently coercing would mask a
    bug in the calling code's result shape.
    """
    if isinstance(obj, Path):
        return str(obj)
    if isinstance(obj, datetime):
        return obj.isoformat()
    raise TypeError(f"object of type {type(obj).__name__} is not JSON-serialisable")


def resolve_db_path(arg: str | None) -> Path:
    """Resolve the ``--db`` flag the same way every ``pf-*`` script does.

    Priority: explicit ``--db`` arg > ``MONOBANK_MCP_DATA_DIR`` env var
    > ``~/finances/data.db``. The env var honours the shared override
    used by the ingest plugins so a single setting reroutes everyone.
    """
    if arg:
        return Path(arg).expanduser()
    env = os.environ.get("MONOBANK_MCP_DATA_DIR")
    if env:
        return Path(env).expanduser() / "data.db"
    return Path.home() / "finances" / "data.db"


def parse_time_arg(value: str, *, flag: str) -> int:
    """Parse a ``--from`` / ``--to`` argument as unix seconds.

    Accepts:
    - an integer string (``"1745107200"``) - interpreted as unix s
    - an ISO 8601 date (``"2026-04-01"``) - midnight UTC
    - an ISO 8601 datetime (``"2026-04-01T12:30:00"`` or with ``Z``) -
      attached to UTC when no tz is present

    ``CliError`` on anything else so the failure surfaces through the
    JSON-error contract instead of as an argparse traceback.
    """
    text = value.strip()
    if not text:
        raise CliError(f"{flag}: empty value")
    if text.lstrip("-").isdigit():
        return int(text)
    iso = text.replace("Z", "+00:00")
    try:
        dt = datetime.fromisoformat(iso)
    except ValueError as exc:
        raise CliError(
            f"{flag}: cannot parse {value!r} as unix-s or ISO 8601 ({exc})",
            kind="ValueError",
        ) from exc
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return int(dt.timestamp())
