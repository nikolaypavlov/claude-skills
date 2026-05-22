"""End-to-end query tests through the umbrella read path."""

from __future__ import annotations

from pathlib import Path

import pytest

from pf_skill.common import queries, store


def test_list_accounts_unions_both_banks(both_banks_db: Path) -> None:
    conn = store.open_db(both_banks_db)
    accounts = queries.list_accounts(conn)
    banks = sorted({a["bank"] for a in accounts})
    assert banks == ["mono", "privat"]
    assert len(accounts) == 2


def test_list_accounts_empty_returns_empty_list(empty_db: Path) -> None:
    conn = store.open_db(empty_db)
    assert queries.list_accounts(conn) == []


def test_get_transactions_returns_both_banks(both_banks_db: Path) -> None:
    conn = store.open_db(both_banks_db)
    txs = queries.get_transactions(conn, limit=100)
    banks = {tx["bank"] for tx in txs}
    assert banks == {"mono", "privat"}
    assert len(txs) == 5  # 3 mono + 2 privat from fixture


def test_get_transactions_filter_by_bank(both_banks_db: Path) -> None:
    conn = store.open_db(both_banks_db)
    txs = queries.get_transactions(conn, bank="privat", limit=100)
    assert all(tx["bank"] == "privat" for tx in txs)
    assert len(txs) == 2


def test_get_transactions_time_range(both_banks_db: Path) -> None:
    conn = store.open_db(both_banks_db)
    # Fixture mono ts: 1_700_000_000 + {0, 1000, 2000}
    # Fixture privat ts: 1_700_000_000 + {10000, 11000}
    txs = queries.get_transactions(
        conn, from_ts=1_700_001_500, to_ts=1_700_010_500, limit=100
    )
    ids = sorted(tx["id"] for tx in txs)
    assert ids == ["mono_t3", "privat_h_1"]


def test_get_transactions_category_resolution(both_banks_db: Path) -> None:
    """Manual override beats rule-assigned category; both populate the
    `category` field returned by `get_transactions`."""
    conn = store.open_db(both_banks_db)
    # Mock rule-assigned category on one mono tx.
    conn.execute(
        "INSERT INTO tx_category (tx_id, category, rule_id, set_at, set_by) "
        "VALUES ('mono_t1', 'rule-category', NULL, 0, 'rule')"
    )
    # And a manual override on another.
    conn.execute(
        "INSERT INTO category_overrides (tx_id, category, note, set_at) "
        "VALUES ('mono_t2', 'override-category', 'pinned', 0)"
    )
    # And BOTH on a third - override should win.
    conn.execute(
        "INSERT INTO tx_category (tx_id, category, rule_id, set_at, set_by) "
        "VALUES ('mono_t3', 'rule-x', NULL, 0, 'rule')"
    )
    conn.execute(
        "INSERT INTO category_overrides (tx_id, category, note, set_at) "
        "VALUES ('mono_t3', 'override-y', NULL, 0)"
    )

    by_id = {tx["id"]: tx for tx in queries.get_transactions(conn, limit=100)}
    assert by_id["mono_t1"]["category"] == "rule-category"
    assert by_id["mono_t2"]["category"] == "override-category"
    assert by_id["mono_t3"]["category"] == "override-y"  # override > rule
    assert by_id["privat_h_1"]["category"] is None  # never categorized


def test_summarize_spending_by_currency(both_banks_db: Path) -> None:
    conn = store.open_db(both_banks_db)
    buckets = queries.summarize_spending(
        conn,
        from_ts=0,
        to_ts=2_000_000_000,
        group_by="currency",
    )
    by_key = {(b["key"], b["currency_code"]): b for b in buckets}
    # Single key per currency since group_by='currency' uses currency_code.
    # All five fixture rows are UAH (980).
    assert ("980", 980) in by_key
    assert by_key[("980", 980)]["tx_count"] == 5


def test_summarize_spending_by_bank(both_banks_db: Path) -> None:
    conn = store.open_db(both_banks_db)
    buckets = queries.summarize_spending(
        conn, from_ts=0, to_ts=2_000_000_000, group_by="bank"
    )
    by_key = {b["key"]: b for b in buckets}
    assert by_key["mono"]["tx_count"] == 3
    assert by_key["privat"]["tx_count"] == 2
    # Mono: -25000 -150000 +500000 = +325000 (signed minor units)
    assert by_key["mono"]["total_minor"] == 325_000


def test_summarize_spending_rejects_unknown_group_by(both_banks_db: Path) -> None:
    conn = store.open_db(both_banks_db)
    with pytest.raises(ValueError, match="unsupported group_by"):
        queries.summarize_spending(
            conn, from_ts=0, to_ts=2_000_000_000, group_by="bogus"
        )


def test_summarize_spending_empty_db(empty_db: Path) -> None:
    conn = store.open_db(empty_db)
    assert queries.summarize_spending(conn, from_ts=0, to_ts=2_000_000_000) == []


def test_find_transactions_substring(both_banks_db: Path) -> None:
    conn = store.open_db(both_banks_db)
    rows = queries.find_transactions(conn, query="GROCERY")
    assert len(rows) == 1
    assert rows[0]["id"] == "mono_t2"


def test_find_transactions_case_insensitive_across_counterparty(
    both_banks_db: Path,
) -> None:
    conn = store.open_db(both_banks_db)
    # "Aroma Kava" lives in counterparty, not description.
    rows = queries.find_transactions(conn, query="aroma")
    assert len(rows) == 1
    assert rows[0]["id"] == "mono_t1"


def test_find_transactions_rejects_empty_query(both_banks_db: Path) -> None:
    conn = store.open_db(both_banks_db)
    with pytest.raises(ValueError, match="non-empty"):
        queries.find_transactions(conn, query="   ")


def test_find_transactions_escapes_like_wildcards(both_banks_db: Path) -> None:
    """A literal underscore in the user input must NOT degenerate into
    LIKE's 'any character' wildcard. Tests that searching for "_" does
    NOT return all rows."""
    conn = store.open_db(both_banks_db)
    rows = queries.find_transactions(conn, query="_")
    # None of the fixture descriptions contain a literal underscore.
    assert rows == []
