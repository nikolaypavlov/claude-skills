"""Typed result shapes for the umbrella query layer.

These TypedDicts mirror the columns returned from the dynamic UNION
ALL projection in ``view.py``. They are NOT a database schema - they
exist so CLI entry points and tests can statically index returned
dicts without ``# type: ignore``.
"""

from __future__ import annotations

from typing import TypedDict


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
