"""Smoke tests for the MCP tool surface.

We don't drive the full stdio handshake here - that's an integration
concern. Instead we build the FastMCP server with an injected DB path
and call the registered tool functions directly to verify they wire to
the right query helpers and produce JSON-serialisable results.
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest
from pf_server.tools import build_server


def _call_tool(server, name: str, **kwargs):
    """Invoke a registered tool by name and unwrap the structured
    content. FastMCP's tool manager wraps the raw return in a list of
    Content blocks; for our pure-JSON tools the structured payload is
    what callers actually see."""
    result = asyncio.run(server._tool_manager.call_tool(name, kwargs))
    # FastMCP returns a tuple (content_list, structured_dict) from
    # call_tool; the structured_dict carries the raw python value.
    if isinstance(result, tuple) and len(result) == 2:
        return result[1] if result[1] is not None else result[0]
    return result


def test_data_sources_empty(empty_db: Path) -> None:
    server = build_server(db_path=empty_db)
    out = _call_tool(server, "data_sources")
    assert out["detected_banks"] == []
    assert out["pf_schema_version"] == 1
    assert "No <bank>_transactions tables detected" in (out["warning"] or "")


def test_data_sources_both_banks(both_banks_db: Path) -> None:
    server = build_server(db_path=both_banks_db)
    out = _call_tool(server, "data_sources")
    assert sorted(out["detected_banks"]) == ["mono", "privat"]
    assert out["warning"] is None


def test_list_accounts_via_tool(both_banks_db: Path) -> None:
    server = build_server(db_path=both_banks_db)
    out = _call_tool(server, "list_accounts")
    # Tool result is a `result` wrapper around the list - the
    # structured payload mirrors what the LLM sees.
    accounts = out["result"] if isinstance(out, dict) and "result" in out else out
    assert isinstance(accounts, list)
    assert len(accounts) == 2
    banks = sorted(a["bank"] for a in accounts)
    assert banks == ["mono", "privat"]


def test_get_transactions_via_tool(both_banks_db: Path) -> None:
    server = build_server(db_path=both_banks_db)
    out = _call_tool(server, "get_transactions", limit=100)
    txs = out["result"] if isinstance(out, dict) and "result" in out else out
    assert isinstance(txs, list)
    assert len(txs) == 5
    # Every dict must serialise cleanly to JSON.
    json.dumps(txs, ensure_ascii=False)


def test_get_transactions_rejects_bad_limit(both_banks_db: Path) -> None:
    server = build_server(db_path=both_banks_db)
    # The tool wrapper validates `limit` and raises ToolError; FastMCP
    # turns that into a structured tool-error response on the wire and
    # re-raises Python-side. Using pytest.raises here so a regression
    # where the exception is swallowed (test passes green with no
    # validation) fails loudly.
    with pytest.raises(Exception, match="limit must be"):
        _call_tool(server, "get_transactions", limit=0)


def test_pr4_tool_raises(both_banks_db: Path) -> None:
    server = build_server(db_path=both_banks_db)
    with pytest.raises(Exception, match="PR#4"):
        _call_tool(server, "set_category", tx_id="mono_t1", category="x")
