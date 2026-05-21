"""MCP tool surface for the personal-finance umbrella server.

PR#3 lands the three read-path tools (``list_accounts``,
``get_transactions``, ``summarize_spending``) plus a diagnostic
(``data_sources``). The remaining tools from the design (`find_*`,
`get_report_bundle`, `set_category`, `add_rule`, `reload_rules`,
`apply_rules_retroactively`, `categorize_uncategorized`) ship in PR#4
and are registered here as no-op stubs from a metadata table so the
schema shape is visible to discovery clients without 7x boilerplate.

Tool errors are raised as ``mcp.server.fastmcp.exceptions.ToolError``
so FastMCP serialises them into a structured tool-error response on the
wire (rather than letting them escape as server-level exceptions).
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from mcp.server.fastmcp import FastMCP
from mcp.server.fastmcp.exceptions import ToolError

from . import queries, store
from .types import DataSourcesReport
from .view import discover_sources

_NOT_YET_IMPLEMENTED = (
    "This tool ships in PR#4 (personal-finance rules + reports). "
    "PR#3 only exposes the read-path skeleton: list_accounts, "
    "get_transactions, summarize_spending, data_sources."
)


def _pr4_stub() -> Any:
    """Shared body for every PR#4 placeholder tool. FastMCP infers each
    tool's parameter schema from the function signature, so we keep the
    PR#4 surface as seven explicit functions below with realistic
    arguments (rather than a metadata-driven loop with ``**kwargs``,
    which the SDK rejects). All of them just delegate here."""
    raise ToolError(_NOT_YET_IMPLEMENTED)


def build_server(db_path: str | Path | None = None) -> FastMCP:
    """Wire every tool to a freshly-opened connection per call.

    SQLite connections are cheap to create and not thread-safe to
    share, so we re-open on each tool invocation. Pass an explicit
    ``db_path`` only in tests; production reads
    ``MONOBANK_MCP_DATA_DIR`` / falls back to ``~/finances/data.db``.
    """
    server: FastMCP = FastMCP(
        name="personal-finance",
        instructions=(
            "Cross-bank query surface over the shared ~/finances/data.db "
            "SQLite store. Auto-discovers <bank>_transactions tables "
            "produced by ingest plugins (monobank-mcp, privat24-skill). "
            "Reads pf_* tables for categories and manual overrides. "
            "PR#3 ships the read path; rules / reports / categorization "
            "land in PR#4."
        ),
    )

    def _open():
        return store.open_db(db_path)

    @server.tool(
        description=(
            "Diagnostic: list which ingest plugins are visible in the "
            "shared store, plus the pf_* schema version. Returns "
            "detected_banks=[] with a warning when no ingest plugin is "
            "installed yet, so the LLM can prompt the user to install "
            "monobank-mcp / privat24-skill."
        )
    )
    def data_sources() -> DataSourcesReport:
        conn = _open()
        try:
            sources = discover_sources(conn)
            pf_version = store.schema_version(conn)
            warning = None
            if not sources.tx_banks:
                warning = (
                    "No <bank>_transactions tables detected. Install at "
                    "least one ingest plugin (monobank-mcp or "
                    "privat24-skill) and run its setup / import flow "
                    "before querying."
                )
            return DataSourcesReport(
                detected_banks=list(sources.tx_banks),
                pf_schema_version=pf_version,
                db_path=str(store.default_db_path() if db_path is None else db_path),
                warning=warning,
            )
        finally:
            conn.close()

    @server.tool(
        description=(
            "List every account row from every ingest plugin currently "
            "installed (mono_accounts + privat_accounts at the time of "
            "writing). Returns [] with no error when the store is empty - "
            "call `data_sources` first if you want to know why."
        )
    )
    def list_accounts() -> list[dict[str, Any]]:
        conn = _open()
        try:
            return [dict(a) for a in queries.list_accounts(conn)]
        finally:
            conn.close()

    @server.tool(
        description=(
            "Cross-bank transaction query with optional filters and "
            "pagination. Returns rows in DESC `ts` order with the "
            "resolved category stitched in (manual override wins over "
            "rule-assigned wins over NULL). Pass `from_ts`/`to_ts` as "
            "inclusive-lower / exclusive-upper unix seconds; "
            "`account_id`, `bank` ('mono'|'privat'|...), `category`, "
            "and `currency_code` (ISO 4217 numeric) further narrow the "
            "result. Default limit is 500; bump up to 5000 if you need "
            "a wider window."
        )
    )
    def get_transactions(
        from_ts: int | None = None,
        to_ts: int | None = None,
        account_id: str | None = None,
        bank: str | None = None,
        category: str | None = None,
        currency_code: int | None = None,
        limit: int = 500,
        offset: int = 0,
    ) -> list[dict[str, Any]]:
        if limit < 1 or limit > 5000:
            raise ToolError(f"limit must be in [1, 5000], got {limit}")
        conn = _open()
        try:
            txs = queries.get_transactions(
                conn,
                from_ts=from_ts,
                to_ts=to_ts,
                account_id=account_id,
                bank=bank,
                category=category,
                currency_code=currency_code,
                limit=limit,
                offset=offset,
            )
            return [dict(t) for t in txs]
        finally:
            conn.close()

    @server.tool(
        description=(
            "Aggregate transactions over [from_ts, to_ts) grouped by "
            "`group_by` ('category' | 'mcc' | 'counterparty' | "
            "'currency' | 'account' | 'bank'). Returns one row per "
            "(key, currency_code) pair with signed minor-unit totals "
            "and tx counts. Multi-currency results are intentional - "
            "we never auto-convert between currencies."
        )
    )
    def summarize_spending(
        from_ts: int,
        to_ts: int,
        group_by: str = "category",
        account_id: str | None = None,
        bank: str | None = None,
        currency_code: int | None = None,
    ) -> list[dict[str, Any]]:
        conn = _open()
        try:
            try:
                buckets = queries.summarize_spending(
                    conn,
                    from_ts=from_ts,
                    to_ts=to_ts,
                    group_by=group_by,
                    account_id=account_id,
                    bank=bank,
                    currency_code=currency_code,
                )
            except ValueError as exc:
                # `_group_by_expression` raises ValueError on an unknown
                # group_by. Surface it as a clean tool-error so the LLM
                # gets the canonical valid-values list.
                raise ToolError(str(exc)) from exc
            return [dict(b) for b in buckets]
        finally:
            conn.close()

    # PR#4 placeholders. Each has a realistic signature so FastMCP
    # publishes the parameter schema discovery clients will need in
    # PR#4. Bodies just delegate to _pr4_stub().

    @server.tool(
        description="Search transactions by description substring. Ships in PR#4."
    )
    def find_transaction(query: str, limit: int = 50) -> Any:
        return _pr4_stub()

    @server.tool(
        description="Build a full report bundle for the given period. Ships in PR#4."
    )
    def get_report_bundle(
        from_ts: int,
        to_ts: int,
        account_id: str | None = None,
        bank: str | None = None,
        comparison: bool = True,
    ) -> Any:
        return _pr4_stub()

    @server.tool(description="Pin a manual category on a specific tx. Ships in PR#4.")
    def set_category(tx_id: str, category: str, note: str | None = None) -> Any:
        return _pr4_stub()

    @server.tool(description="Add a categorization rule (preview-only). Ships in PR#4.")
    def add_rule(
        match_field: str,
        pattern: str,
        category: str,
        priority: int = 100,
        source: str = "claude-suggested",
    ) -> Any:
        return _pr4_stub()

    @server.tool(
        description="Reload categorization rules from the YAML / DB sources. Ships in PR#4."
    )
    def reload_rules() -> Any:
        return _pr4_stub()

    @server.tool(
        description="Apply a rule retroactively to historical transactions. Ships in PR#4."
    )
    def apply_rules_retroactively(rule_id: int, dry_run: bool = True) -> Any:
        return _pr4_stub()

    @server.tool(
        description="Categorize all uncategorized transactions. Ships in PR#4."
    )
    def categorize_uncategorized(scope: str = "all") -> Any:
        return _pr4_stub()

    return server
