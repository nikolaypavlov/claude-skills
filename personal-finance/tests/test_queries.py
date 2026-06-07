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
    txs = queries.get_transactions(conn, from_ts=1_700_001_500, to_ts=1_700_010_500, limit=100)
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


def test_get_transactions_category_filter(both_banks_db: Path) -> None:
    """``category="X"`` returns only rows resolved to X; ``category=""`` is
    the uncategorized sentinel and returns rows with NULL resolved
    category (no rule, no override). The empty-string special-casing is
    load-bearing for the `pf-query list --category ""` invocation in
    SKILL.md."""
    conn = store.open_db(both_banks_db)
    # Categorize 2 of the 5 fixture rows; leave the other 3 uncategorized.
    conn.execute(
        "INSERT INTO tx_category (tx_id, category, rule_id, set_at, set_by) "
        "VALUES ('mono_t1', 'Food', NULL, 0, 'rule')"
    )
    conn.execute(
        "INSERT INTO category_overrides (tx_id, category, note, set_at) "
        "VALUES ('mono_t2', 'Transport', NULL, 0)"
    )

    food = queries.get_transactions(conn, category="Food", limit=100)
    assert [tx["id"] for tx in food] == ["mono_t1"]

    transport = queries.get_transactions(conn, category="Transport", limit=100)
    assert [tx["id"] for tx in transport] == ["mono_t2"]

    uncategorized = queries.get_transactions(conn, category="", limit=100)
    uncat_ids = sorted(tx["id"] for tx in uncategorized)
    assert uncat_ids == ["mono_t3", "privat_h_1", "privat_h_2"]
    assert all(tx["category"] is None for tx in uncategorized)


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
    buckets = queries.summarize_spending(conn, from_ts=0, to_ts=2_000_000_000, group_by="bank")
    by_key = {b["key"]: b for b in buckets}
    assert by_key["mono"]["tx_count"] == 3
    assert by_key["privat"]["tx_count"] == 2
    # Mono: -25000 -150000 +500000 = +325000 (signed minor units)
    assert by_key["mono"]["total_minor"] == 325_000


def test_summarize_spending_rejects_unknown_group_by(both_banks_db: Path) -> None:
    conn = store.open_db(both_banks_db)
    with pytest.raises(ValueError, match="unsupported group_by"):
        queries.summarize_spending(conn, from_ts=0, to_ts=2_000_000_000, group_by="bogus")


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


def test_list_categories_empty_when_nothing_assigned(both_banks_db: Path) -> None:
    """No rows in tx_category or category_overrides yet -> empty list."""
    conn = store.open_db(both_banks_db)
    assert queries.list_categories(conn) == []


def test_list_categories_counts_rule_assignments(both_banks_db: Path) -> None:
    conn = store.open_db(both_banks_db)
    conn.execute(
        "INSERT INTO tx_category (tx_id, category, rule_id, set_at, set_by) "
        "VALUES ('mono_t1', 'Food', NULL, 0, 'rule'), "
        "('mono_t2', 'Food', NULL, 0, 'rule'), "
        "('mono_t3', 'Salary', NULL, 0, 'rule')"
    )
    cats = queries.list_categories(conn)
    by = {c["category"]: c["tx_count"] for c in cats}
    assert by == {"Food": 2, "Salary": 1}
    # tx_count desc sort: Food (2) before Salary (1)
    assert cats[0]["category"] == "Food"
    assert cats[1]["category"] == "Salary"


def test_list_categories_override_replaces_rule_category(both_banks_db: Path) -> None:
    """An overridden tx counts toward the override category, not the
    rule-assigned one. The rule's category is dropped if no other tx
    holds it."""
    conn = store.open_db(both_banks_db)
    conn.execute(
        "INSERT INTO tx_category (tx_id, category, rule_id, set_at, set_by) "
        "VALUES ('mono_t1', 'Food', NULL, 0, 'rule')"
    )
    conn.execute(
        "INSERT INTO category_overrides (tx_id, category, note, set_at) "
        "VALUES ('mono_t1', 'Gifts', NULL, 0)"
    )
    by = {c["category"]: c["tx_count"] for c in queries.list_categories(conn)}
    assert by == {"Gifts": 1}
    assert "Food" not in by


def test_list_categories_override_only_tx_appears(both_banks_db: Path) -> None:
    """A tx with only a category_override (never matched by a rule) still
    shows up in the listing."""
    conn = store.open_db(both_banks_db)
    conn.execute(
        "INSERT INTO category_overrides (tx_id, category, note, set_at) "
        "VALUES ('privat_h_1', 'Manual', 'pinned', 0)"
    )
    by = {c["category"]: c["tx_count"] for c in queries.list_categories(conn)}
    assert by == {"Manual": 1}


def test_summarize_uncategorized_returns_all_when_nothing_categorized(
    both_banks_db: Path,
) -> None:
    conn = store.open_db(both_banks_db)
    buckets = queries.summarize_uncategorized(conn, group_by="description")
    by = {b["key"]: b["tx_count"] for b in buckets}
    # Fixture: 3 mono + 2 privat, each with a distinct description.
    assert by == {
        "Coffee shop": 1,
        "Grocery shop": 1,
        "Salary": 1,
        "Privat shop": 1,
        "EUR transfer": 1,
    }


def test_summarize_uncategorized_excludes_categorized(both_banks_db: Path) -> None:
    conn = store.open_db(both_banks_db)
    conn.execute(
        "INSERT INTO tx_category (tx_id, category, rule_id, set_at, set_by) "
        "VALUES ('mono_t1', 'Food', NULL, 0, 'rule'), "
        "('mono_t3', 'Salary', NULL, 0, 'rule')"
    )
    by = {b["key"]: b["tx_count"] for b in queries.summarize_uncategorized(conn)}
    assert "Coffee shop" not in by  # mono_t1 categorized
    assert "Salary" not in by  # mono_t3 categorized
    assert by == {"Grocery shop": 1, "Privat shop": 1, "EUR transfer": 1}


def test_summarize_uncategorized_excludes_overridden(both_banks_db: Path) -> None:
    """An override (no rule needed) makes the tx categorized for the
    purposes of this listing."""
    conn = store.open_db(both_banks_db)
    conn.execute(
        "INSERT INTO category_overrides (tx_id, category, note, set_at) "
        "VALUES ('mono_t1', 'Coffee', NULL, 0)"
    )
    by = {b["key"]: b["tx_count"] for b in queries.summarize_uncategorized(conn)}
    assert "Coffee shop" not in by


def test_summarize_uncategorized_group_by_mcc(both_banks_db: Path) -> None:
    conn = store.open_db(both_banks_db)
    buckets = queries.summarize_uncategorized(conn, group_by="mcc")
    by = {b["key"]: b["tx_count"] for b in buckets}
    assert by[5814] == 1  # mono_t1 coffee shop
    assert by[5411] == 1  # mono_t2 grocery
    # mono_t3 (NULL mcc) + 2 privat (NULL mcc) -> 3 rows in NULL bucket
    assert by[None] == 3


def test_summarize_uncategorized_time_range(both_banks_db: Path) -> None:
    """Bound the window so only a subset of fixture rows fall inside."""
    conn = store.open_db(both_banks_db)
    buckets = queries.summarize_uncategorized(conn, from_ts=1_700_001_500, to_ts=1_700_010_500)
    by = {b["key"]: b["tx_count"] for b in buckets}
    # mono_t3 (ts=1_700_002_000) + privat_h_1 (ts=1_700_010_000) only
    assert by == {"Salary": 1, "Privat shop": 1}


def test_summarize_uncategorized_unknown_group_by(both_banks_db: Path) -> None:
    conn = store.open_db(both_banks_db)
    with pytest.raises(ValueError, match="unsupported group_by"):
        queries.summarize_uncategorized(conn, group_by="bank")


# Regression tests for the operation-vs-account currency fix.
#
# The bug: monobank stores ``currency_code`` on each transaction as the
# OPERATION currency. A Patreon charge on a UAH card has
# ``amount_minor`` in UAH kopecks but ``currency_code = 840`` (USD),
# because the merchant billed in USD. Bucketing by ``tx.currency_code``
# files that row under USD even though no USD actually left the account
# and ``amount_minor`` is denominated in UAH. The fix sources the
# bucket dimension from ``<bank>_accounts.currency_code`` instead.
#
# Each test below names the (account_currency, operation_currency,
# expected_bucket) it exercises so a future contributor can extend the
# fixture without losing the regression.


def test_summarize_by_counterparty_uses_account_currency(
    mixed_currency_db: Path,
) -> None:
    """UAH-card + USD-merchant Patreon row buckets to UAH (980), NOT
    USD - even though ``tx.currency_code = 840``. This is the headline
    bug: Patreon was being reported as $213.32 instead of 212.32 UAH."""
    conn = store.open_db(mixed_currency_db)
    buckets = queries.summarize_spending(
        conn, from_ts=0, to_ts=2_000_000_000, group_by="counterparty"
    )
    patreon = next(b for b in buckets if b["key"] == "Patreon")
    assert patreon["currency_code"] == 980  # UAH, the account currency
    assert patreon["total_minor"] == -21232  # the UAH kopecks billed

    apple = next(b for b in buckets if b["key"] == "Apple")
    assert apple["currency_code"] == 980
    assert apple["total_minor"] == -13226


def test_summarize_by_counterparty_same_currency_unchanged(
    mixed_currency_db: Path,
) -> None:
    """USD card + USD merchant (AWS) must STILL bucket to USD - the
    fix must not regress the path where account and operation currencies
    already agree."""
    conn = store.open_db(mixed_currency_db)
    buckets = queries.summarize_spending(
        conn, from_ts=0, to_ts=2_000_000_000, group_by="counterparty"
    )
    aws = next(b for b in buckets if b["key"] == "Amazon")
    assert aws["currency_code"] == 840  # account = operation = USD
    assert aws["total_minor"] == -5500


def test_summarize_group_by_currency_uses_account_currency(
    mixed_currency_db: Path,
) -> None:
    """``--group-by currency`` yields one bucket per ACCOUNT currency,
    not per operation currency. Fixture: 3 UAH-card rows (Patreon,
    Apple, EU train), 2 USD-card rows (AWS, EU cafe), 1 EUR-jar row
    (topup) - so we expect three buckets: 980, 840, 978."""
    conn = store.open_db(mixed_currency_db)
    buckets = queries.summarize_spending(conn, from_ts=0, to_ts=2_000_000_000, group_by="currency")
    by_cur = {b["currency_code"]: b for b in buckets}
    assert set(by_cur.keys()) == {980, 840, 978}
    assert by_cur[980]["tx_count"] == 3
    assert by_cur[840]["tx_count"] == 2
    assert by_cur[978]["tx_count"] == 1
    # UAH total = -21232 (Patreon) + -13226 (Apple) + -50000 (EU train)
    assert by_cur[980]["total_minor"] == -84458
    # USD total = -5500 (AWS) + -3300 (cafe)
    assert by_cur[840]["total_minor"] == -8800


def test_currency_filter_uses_account_currency(mixed_currency_db: Path) -> None:
    """``currency_code=980`` (UAH) on ``get_transactions`` must return the
    UAH-card rows including the USD-merchant Patreon charge - before the
    fix it filtered on the operation currency and silently dropped
    foreign-merchant rows from the UAH bucket."""
    conn = store.open_db(mixed_currency_db)
    uah = queries.get_transactions(conn, currency_code=980, limit=100)
    ids = sorted(tx["id"] for tx in uah)
    assert ids == ["uah_apple", "uah_eur", "uah_patreon"]
    # Every returned row's projected currency_code matches the filter.
    assert all(tx["currency_code"] == 980 for tx in uah)
    # The operation currency is still visible per row.
    by_id = {tx["id"]: tx for tx in uah}
    assert by_id["uah_patreon"]["op_currency_code"] == 840
    assert by_id["uah_patreon"]["op_amount_minor"] == -480

    usd = queries.get_transactions(conn, currency_code=840, limit=100)
    assert sorted(tx["id"] for tx in usd) == ["usd_aws", "usd_eur"]
    # ``--currency USD`` must NOT pick up the UAH-card USD-merchant row.
    assert "uah_patreon" not in {tx["id"] for tx in usd}


def test_per_row_currency_code_is_account_currency(mixed_currency_db: Path) -> None:
    """Per-row ``currency_code`` returned by ``get_transactions`` mirrors
    the account currency so ``amount_minor`` and ``currency_code`` stay
    denominationally consistent. Operation currency lives in
    ``op_currency_code``."""
    conn = store.open_db(mixed_currency_db)
    by_id = {tx["id"]: tx for tx in queries.get_transactions(conn, limit=100)}
    # UAH card / USD merchant: currency_code = UAH (account); op_* = USD.
    assert by_id["uah_patreon"]["currency_code"] == 980
    assert by_id["uah_patreon"]["op_currency_code"] == 840
    # USD card / EUR merchant: currency_code = USD (account); op_* = EUR.
    assert by_id["usd_eur"]["currency_code"] == 840
    assert by_id["usd_eur"]["op_currency_code"] == 978
    # Same-currency tx still has op_* NULL (mono convention).
    assert by_id["usd_aws"]["currency_code"] == 840
    assert by_id["usd_aws"]["op_currency_code"] is None


def test_summarize_uncategorized_uses_account_currency(
    mixed_currency_db: Path,
) -> None:
    """``summarize_uncategorized`` groups by account currency too -
    otherwise the categorize-skill triage view double-reports foreign
    merchants under both UAH and USD lines."""
    conn = store.open_db(mixed_currency_db)
    buckets = queries.summarize_uncategorized(conn, group_by="counterparty")
    by = {b["key"]: b for b in buckets}
    assert by["Patreon"]["currency_code"] == 980
    assert by["Apple"]["currency_code"] == 980
    assert by["Amazon"]["currency_code"] == 840
