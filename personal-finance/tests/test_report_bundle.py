"""Tests for ``pf_skill.common.reports.build_report_bundle`` and the
``pf-report`` CLI wrapper.

Covers:
- Full vs bucketed mode auto-switch at the 90-day threshold.
- ``currencies_seen``, ``active_rules_count``, ``uncategorized_count``.
- ``last_sync_ts``: ``mono_sync_state`` preferred, MAX(imported_at)
  fallback for ``privat``.
- ``comparison`` block when ``--comparison previous-period`` is set.
- Empty-store warning path.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from pf_skill.common import store
from pf_skill.common.reports import FULL_DUMP_THRESHOLD_DAYS, build_report_bundle
from pf_skill.report import main as report_main


def test_full_mode_for_short_period(both_banks_db: Path) -> None:
    conn = store.open_db(both_banks_db)
    # Mode is decided by elapsed wall time of the period (not whether
    # the period covers any fixture rows), so use a real 30-day window.
    short = build_report_bundle(conn, from_ts=1_700_000_000, to_ts=1_700_000_000 + 30 * 86_400)
    assert short["mode"] == "full"
    assert "transactions" in short
    assert "monthly_buckets" not in short


def test_bucketed_mode_for_long_period(both_banks_db: Path) -> None:
    conn = store.open_db(both_banks_db)
    span_s = (FULL_DUMP_THRESHOLD_DAYS + 30) * 86_400
    bundle = build_report_bundle(conn, from_ts=1_700_000_000, to_ts=1_700_000_000 + span_s)
    assert bundle["mode"] == "bucketed"
    assert "monthly_buckets" in bundle
    assert "top_transactions" in bundle
    assert "transactions" not in bundle


def test_currencies_seen_is_distinct(both_banks_db: Path) -> None:
    conn = store.open_db(both_banks_db)
    bundle = build_report_bundle(conn, from_ts=0, to_ts=2_000_000_000)
    assert bundle["currencies_seen"] == [980]


def test_uncategorized_count_reflects_overrides(both_banks_db: Path) -> None:
    conn = store.open_db(both_banks_db)
    # Three uncategorized initially (5 rows, all uncategorized).
    bundle = build_report_bundle(conn, from_ts=0, to_ts=2_000_000_000)
    assert bundle["uncategorized_count"] == 5

    conn.execute(
        "INSERT INTO tx_category (tx_id, category, rule_id, set_at, set_by) "
        "VALUES ('mono_t1', 'Food', NULL, 0, 'rule')"
    )
    conn.execute(
        "INSERT INTO category_overrides (tx_id, category, note, set_at) "
        "VALUES ('privat_h_1', 'Misc', NULL, 0)"
    )
    bundle = build_report_bundle(conn, from_ts=0, to_ts=2_000_000_000)
    assert bundle["uncategorized_count"] == 3


def test_active_rules_count_excludes_disabled(both_banks_db: Path) -> None:
    conn = store.open_db(both_banks_db)
    conn.execute(
        "INSERT INTO categorization_rules "
        "(priority, match_field, pattern, category, enabled, created_at, source) "
        "VALUES (10, 'mcc', '5814', 'Food', 1, 0, 'seed')"
    )
    conn.execute(
        "INSERT INTO categorization_rules "
        "(priority, match_field, pattern, category, enabled, created_at, source) "
        "VALUES (20, 'mcc', '5411', 'Grocery', 0, 0, 'seed')"
    )
    bundle = build_report_bundle(conn, from_ts=0, to_ts=2_000_000_000)
    assert bundle["active_rules_count"] == 1


def test_last_sync_ts_prefers_mono_sync_state(both_banks_db: Path) -> None:
    conn = store.open_db(both_banks_db)
    bundle = build_report_bundle(conn, from_ts=0, to_ts=2_000_000_000)
    # Fixture: mono_sync_state seeded with 1_700_050_000.
    assert bundle["last_sync_ts"]["mono"] == 1_700_050_000
    # Privat falls back to MAX(imported_at) - fixture sets it to
    # 1_700_100_000.
    assert bundle["last_sync_ts"]["privat"] == 1_700_100_000


def test_comparison_previous_period(both_banks_db: Path) -> None:
    conn = store.open_db(both_banks_db)
    # Window covers mono_t3 (+500000) and privat_h_1 (-33333).
    bundle = build_report_bundle(
        conn,
        from_ts=1_700_001_500,
        to_ts=1_700_010_500,
        comparison="previous-period",
    )
    assert "comparison" in bundle
    prev = bundle["comparison"]["previous_period"]
    span = 1_700_010_500 - 1_700_001_500
    assert prev["from_ts"] == 1_700_001_500 - span
    assert prev["to_ts"] == 1_700_001_500
    # Per-currency block exists.
    assert isinstance(bundle["comparison"]["per_currency"], list)


def test_bundle_buckets_use_account_currency(mixed_currency_db: Path) -> None:
    """``currencies_seen``, ``monthly_buckets``, and the per-currency
    in/out comparison all report ACCOUNT currency. A UAH-card Patreon
    charge with ``tx.currency_code = 840`` must not leak into the USD
    line of any report dimension."""
    conn = store.open_db(mixed_currency_db)
    span_s = (FULL_DUMP_THRESHOLD_DAYS + 30) * 86_400
    bundle = build_report_bundle(
        conn,
        from_ts=1_700_000_000 - 86_400,
        to_ts=1_700_000_000 + span_s,
        comparison="previous-period",
    )

    # currencies_seen: three account currencies, not four (would have
    # been 980, 840, 978 + duplicate 840 from operation-currency view).
    assert bundle["currencies_seen"] == [840, 978, 980]

    # monthly_buckets bucket by account currency: Patreon shows up
    # under 980 with the UAH kopecks amount.
    patreon_buckets = [
        b for b in bundle["monthly_buckets"] if (b.get("category") or "") == "(uncategorized)"
    ]
    by_cur = {(b["currency_code"], b["total_minor"]) for b in patreon_buckets}
    # Patreon -21232 in UAH (980) must be present; -480 in USD (840)
    # must NOT be present.
    assert any(cur == 980 and total <= -21232 for cur, total in by_cur)
    assert not any(cur == 840 and total == -480 for cur, total in by_cur)

    # comparison.per_currency: one entry per account currency.
    per_cur = {row["currency_code"] for row in bundle["comparison"]["per_currency"]}
    assert per_cur == {840, 978, 980}


def test_empty_db_returns_warning_bundle(empty_db: Path) -> None:
    conn = store.open_db(empty_db)
    bundle = build_report_bundle(conn, from_ts=1_700_000_000, to_ts=1_700_000_000 + 30 * 86_400)
    assert bundle["ok"] is True
    assert bundle["accounts"] == []
    assert bundle["currencies_seen"] == []
    assert "warning" in bundle


def test_cli_outputs_bundle_json(both_banks_db: Path, capsys: pytest.CaptureFixture[str]) -> None:
    rc = report_main(
        [
            "--from",
            "1700000000",
            "--to",
            "1700100000",
            "--db",
            str(both_banks_db),
        ]
    )
    captured = capsys.readouterr()
    assert rc == 0, captured.err
    payload = json.loads(captured.out)
    assert payload["ok"] is True
    assert payload["mode"] == "full"
    assert payload["period"]["from_ts"] == 1_700_000_000


def test_cli_rejects_inverted_range(
    both_banks_db: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    rc = report_main(
        [
            "--from",
            "1700100000",
            "--to",
            "1700000000",
            "--db",
            str(both_banks_db),
        ]
    )
    captured = capsys.readouterr()
    assert rc == 1
    err = json.loads(captured.err)
    assert err["ok"] is False
    assert "strictly less" in err["error"]


def test_cli_unknown_comparison_rejected(
    both_banks_db: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    rc = report_main(
        [
            "--from",
            "1700000000",
            "--to",
            "1700100000",
            "--comparison",
            "fancy-thing",
            "--db",
            str(both_banks_db),
        ]
    )
    captured = capsys.readouterr()
    assert rc == 1
    err = json.loads(captured.err)
    assert err["ok"] is False
