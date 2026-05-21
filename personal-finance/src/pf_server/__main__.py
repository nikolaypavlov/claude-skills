"""Entry point for ``uv run pf-server``.

Boots the FastMCP server over stdio so Claude Desktop / Claude Code
can spawn it from ``.mcp.json``. Reading from ``MONOBANK_MCP_DATA_DIR``
(or the default ``~/finances/data.db``) keeps the umbrella in sync with
the ingest plugins without a separate config file.
"""

from __future__ import annotations

import os
import sys

from .tools import build_server


def main() -> int:
    # Run-once probe path is useful for setup wizards / health checks
    # without a full MCP handshake.
    if "--probe" in sys.argv:
        return _probe()
    server = build_server()
    server.run()  # stdio transport, blocks until client disconnects
    return 0


def _probe() -> int:
    """Smoke check: open the DB, run discovery, print one-line JSON."""
    import json

    from . import store
    from .view import discover_sources

    try:
        conn = store.open_db()
        try:
            sources = discover_sources(conn)
            version = store.schema_version(conn)
        finally:
            conn.close()
        out = {
            "ok": True,
            "pf_schema_version": version,
            "detected_banks": list(sources.tx_banks),
            "db_path": str(store.default_db_path()),
            "env_data_dir": os.environ.get("MONOBANK_MCP_DATA_DIR"),
        }
        print(json.dumps(out, indent=2))
        return 0
    except Exception as exc:  # noqa: BLE001 - probe must always emit JSON
        print(json.dumps({"ok": False, "error": str(exc)}, indent=2))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
