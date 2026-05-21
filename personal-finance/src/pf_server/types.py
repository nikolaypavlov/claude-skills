"""Typed result shapes for the umbrella query layer.

These TypedDicts mirror the columns returned from the dynamic UNION
ALL projection in ``view.py``. They are NOT a database schema - they
exist so MCP tool callers and tests can statically index returned
dicts without ``# type: ignore``.
"""

from __future__ import annotations

from typing import Literal, TypedDict

# `bank` field of every projected row. New banks land here when their
# ingest plugin lands. The umbrella server doesn't reject unknown
# values at runtime (the view discovery is dynamic), but the Literal
# helps type-check fixtures and assertions.
Bank = Literal["mono", "privat"]


class Account(TypedDict):
    """Projected row from the discovered ``<bank>_accounts`` UNION."""

    account_id: str
    bank: str
    iban: str | None
    type: str | None
    currency_code: int
    masked_pan: str | None
    label: str | None
    opened_at: int | None


class Transaction(TypedDict):
    """Projected row from the discovered ``<bank>_transactions`` UNION.

    Plus the resolved ``category`` field stitched in by
    ``get_transactions``: ``category_overrides`` wins over
    ``tx_category`` wins over NULL.
    """

    id: str
    bank: str
    account_id: str
    ts: int
    amount_minor: int
    currency_code: int
    op_amount_minor: int | None
    op_currency_code: int | None
    mcc: int | None
    description: str | None
    counterparty: str | None
    balance_minor: int | None
    imported_at: int
    category: str | None


class SummaryBucket(TypedDict):
    """One row from ``summarize_spending``: aggregated total per
    grouping key per currency."""

    key: str
    currency_code: int
    total_minor: int
    tx_count: int


class DataSourcesReport(TypedDict):
    """Diagnostic shape returned when the store is empty so the LLM
    can tell the user "install at least one ingest plugin"."""

    detected_banks: list[str]
    pf_schema_version: int
    db_path: str
    warning: str | None
