"""End-to-end categorizer tests.

Uses the synthetic mono_* / privat_* fixtures from conftest.py plus the
real seed rules (description.yaml, mcc.json). Asserts on what gets
written to tx_category / category_overrides under different scenarios.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from pf_skill.common import store
from pf_skill.common.categorizer import (
    apply_rule_by_id,
    apply_rules,
    preview_rule,
)


def _all_categorized(conn) -> dict[str, str]:
    return {
        r[0]: r[1] for r in conn.execute("SELECT tx_id, category FROM tx_category ORDER BY tx_id")
    }


def test_apply_rules_writes_tx_category(both_banks_db: Path) -> None:
    conn = store.open_db(both_banks_db)
    result = apply_rules(conn, scope="all", data_dir=both_banks_db.parent)
    # 5 fixture tx total; mono_t1 (5814) and mono_t2 (5411) match seed MCC
    # rules; mono_t3 has NULL MCC + "Salary" description -> no match;
    # privat_h_1 ("Privat shop") + privat_h_2 ("EUR transfer") -> no MCC,
    # no seed description match.
    cats = _all_categorized(conn)
    assert "mono_t1" in cats
    assert "mono_t2" in cats
    assert cats["mono_t1"] == "Їжа/Фастфуд"  # MCC 5814
    assert cats["mono_t2"] == "Їжа/Продукти"  # MCC 5411
    assert "mono_t3" not in cats  # no match
    assert "privat_h_1" not in cats
    assert "privat_h_2" not in cats
    assert result["categorized_count"] == 2
    assert result["no_match_count"] == 3
    assert result["overrides_applied"] == 0
    assert result["active_rules"] > 0


def test_apply_rules_priority_resolution(both_banks_db: Path) -> None:
    """Description rule (priority 100) wins over MCC rule (priority
    300) when both would match. Insert a DB rule that matches mono_t1
    by description at priority 50; assert that one (not the MCC fallback)
    is what ends up in tx_category."""
    conn = store.open_db(both_banks_db)
    conn.execute(
        "INSERT INTO categorization_rules "
        "(priority, match_field, pattern, category, enabled, created_at, source) "
        "VALUES (50, 'description', '(?i)coffee', 'Їжа/Кафе', 1, 0, 'user')"
    )
    apply_rules(conn, scope="all", data_dir=both_banks_db.parent)
    cats = _all_categorized(conn)
    assert cats["mono_t1"] == "Їжа/Кафе"  # custom rule beat MCC fallback


def test_apply_rules_skips_already_categorized(both_banks_db: Path) -> None:
    conn = store.open_db(both_banks_db)
    apply_rules(conn, scope="all", data_dir=both_banks_db.parent)
    # Second pass should categorize nothing new.
    result = apply_rules(conn, scope="all", data_dir=both_banks_db.parent)
    assert result["categorized_count"] == 0
    # The unmatched ones stay unmatched.
    assert result["no_match_count"] == 3


def test_apply_rules_empty_db(empty_db: Path) -> None:
    conn = store.open_db(empty_db)
    result = apply_rules(conn, scope="all", data_dir=empty_db.parent)
    assert result["categorized_count"] == 0
    assert result["no_match_count"] == 0
    assert result["overrides_applied"] == 0
    # Active rules is still > 0 - seed rules load even with no tx source.
    assert result["active_rules"] > 0


def test_apply_rules_scope_last_n_days(both_banks_db: Path) -> None:
    """``last-n-days`` filters by tx.ts; with n=1 and now=ts after the
    fixtures, nothing should be in scope (fixtures are years in the past
    relative to now). With now far in the past + n large, everything is."""
    conn = store.open_db(both_banks_db)
    # All fixture tx are ts ~ 1_700_000_000. Use n=1 and now=1_700_500_000:
    # window is [1_700_500_000 - 86400, ...] which excludes fixtures.
    result = apply_rules(
        conn,
        scope="last-n-days",
        n_days=1,
        data_dir=both_banks_db.parent,
        now=1_700_500_000,
    )
    assert result["categorized_count"] == 0


def test_apply_rules_scope_validation(both_banks_db: Path) -> None:
    conn = store.open_db(both_banks_db)
    with pytest.raises(ValueError, match="unsupported scope"):
        apply_rules(conn, scope="bogus", data_dir=both_banks_db.parent)
    with pytest.raises(ValueError, match="positive integer"):
        apply_rules(
            conn,
            scope="last-n-days",
            n_days=0,
            data_dir=both_banks_db.parent,
        )


def test_overrides_upserted_into_category_overrides(both_banks_db: Path) -> None:
    rules_dir = both_banks_db.parent / "rules"
    rules_dir.mkdir(exist_ok=True)
    (rules_dir / "overrides.local.yaml").write_text(
        "- tx_id: mono_t3\n  category: Подарунки\n  note: Birthday\n",
        encoding="utf-8",
    )
    conn = store.open_db(both_banks_db)
    result = apply_rules(conn, scope="all", data_dir=both_banks_db.parent)
    row = conn.execute(
        "SELECT category, note FROM category_overrides WHERE tx_id = 'mono_t3'"
    ).fetchone()
    assert row == ("Подарунки", "Birthday")
    assert result["overrides_applied"] == 1


def test_override_beats_rule_at_query_time(both_banks_db: Path) -> None:
    """A row pinned via category_overrides must NOT be touched by the
    categorizer (its uncategorized filter checks the COALESCE expr)."""
    rules_dir = both_banks_db.parent / "rules"
    rules_dir.mkdir(exist_ok=True)
    (rules_dir / "overrides.local.yaml").write_text(
        "- tx_id: mono_t1\n  category: ManualPin\n",
        encoding="utf-8",
    )
    conn = store.open_db(both_banks_db)
    apply_rules(conn, scope="all", data_dir=both_banks_db.parent)
    cats = _all_categorized(conn)
    # mono_t1 was matched by an override BEFORE the rule pass, so the
    # rule pass should not have written a tx_category row for it.
    assert "mono_t1" not in cats


def test_preview_rule_counts_and_samples(both_banks_db: Path) -> None:
    conn = store.open_db(both_banks_db)
    out = preview_rule(
        conn,
        match_field="description",
        pattern="(?i)privat",
        category="Test/Privat",
    )
    assert out["would_affect_count"] == 1  # "Privat shop"
    assert len(out["sample"]) == 1
    assert out["sample"][0]["id"] == "privat_h_1"


def test_preview_empty_store(empty_db: Path) -> None:
    conn = store.open_db(empty_db)
    out = preview_rule(conn, match_field="description", pattern="(?i)x", category="Y")
    assert out["would_affect_count"] == 0
    assert out["sample"] == []


def test_apply_rule_by_id_writes_only_matching(both_banks_db: Path) -> None:
    conn = store.open_db(both_banks_db)
    conn.execute(
        "INSERT INTO categorization_rules "
        "(priority, match_field, pattern, category, enabled, created_at, source) "
        "VALUES (100, 'description', '(?i)EUR transfer', 'FX', 1, 0, 'user')"
    )
    rule_id = conn.execute("SELECT MAX(id) FROM categorization_rules").fetchone()[0]
    result = apply_rule_by_id(conn, rule_id=int(rule_id), dry_run=False)
    assert result["matched_count"] == 1
    assert result["applied"] == 1
    cats = _all_categorized(conn)
    assert cats["privat_h_2"] == "FX"
    # No collateral - only the one match was written.
    assert "privat_h_1" not in cats


def test_apply_rule_by_id_dry_run_writes_nothing(both_banks_db: Path) -> None:
    conn = store.open_db(both_banks_db)
    conn.execute(
        "INSERT INTO categorization_rules "
        "(priority, match_field, pattern, category, enabled, created_at, source) "
        "VALUES (100, 'description', '(?i)EUR transfer', 'FX', 1, 0, 'user')"
    )
    rule_id = conn.execute("SELECT MAX(id) FROM categorization_rules").fetchone()[0]
    result = apply_rule_by_id(conn, rule_id=int(rule_id), dry_run=True)
    assert result["matched_count"] == 1
    assert result["applied"] == 0
    assert _all_categorized(conn) == {}  # nothing written


def test_apply_rule_by_id_unknown_raises(empty_db: Path) -> None:
    conn = store.open_db(empty_db)
    with pytest.raises(ValueError, match="no rule with id"):
        apply_rule_by_id(conn, rule_id=999, dry_run=False)
