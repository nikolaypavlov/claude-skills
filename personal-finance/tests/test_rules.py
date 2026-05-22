"""Rule loading + matching tests.

Covers every source loader plus the regex-matching predicate. Local
YAMLs and the DB are written in tmp_path so the suite never touches a
real ~/finances directory.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from pf_skill.common import store
from pf_skill.common.rules import (
    DEFAULT_PRIORITY_BY_FIELD,
    Rule,
    first_match,
    load_all_rules,
    load_overrides,
)


def test_seed_description_rules_loaded(empty_db: Path) -> None:
    conn = store.open_db(empty_db)
    rules = load_all_rules(conn, data_dir=empty_db.parent)
    desc = [r for r in rules if r.source == "seed-description"]
    assert desc, "expected at least one seed description rule"
    assert all(r.match_field == "description" for r in desc)
    assert all(r.priority == DEFAULT_PRIORITY_BY_FIELD["description"] for r in desc)


def test_seed_mcc_rules_loaded(empty_db: Path) -> None:
    conn = store.open_db(empty_db)
    rules = load_all_rules(conn, data_dir=empty_db.parent)
    mcc = [r for r in rules if r.source == "seed-mcc"]
    assert mcc, "expected at least one seed MCC rule"
    assert all(r.match_field == "mcc" for r in mcc)
    assert all(r.priority == DEFAULT_PRIORITY_BY_FIELD["mcc"] for r in mcc)
    # The _comment key must NOT have become a rule.
    assert not any(r.pattern.startswith("_") for r in mcc)
    # 5814 is a representative MCC; we ship it in the seed.
    assert any(r.pattern == "5814" for r in mcc)


def test_sort_order_puts_description_before_mcc(empty_db: Path) -> None:
    conn = store.open_db(empty_db)
    rules = load_all_rules(conn, data_dir=empty_db.parent)
    # First rule must be priority 100 (description). Last must be >= 300 (mcc).
    assert rules[0].priority == DEFAULT_PRIORITY_BY_FIELD["description"]
    assert rules[-1].priority >= DEFAULT_PRIORITY_BY_FIELD["mcc"]


def test_local_counterparty_missing_is_silent(empty_db: Path) -> None:
    conn = store.open_db(empty_db)
    rules = load_all_rules(conn, data_dir=empty_db.parent)
    # No rules/counterparty.local.yaml in tmp_path -> no local rules in
    # the merged list.
    assert not any(r.source == "local-counterparty" for r in rules)


def test_local_counterparty_loaded(tmp_path: Path) -> None:
    rules_dir = tmp_path / "rules"
    rules_dir.mkdir()
    (rules_dir / "counterparty.local.yaml").write_text(
        "- pattern: 'ACME Corp'\n  category: 'Робота'\n",
        encoding="utf-8",
    )
    db = tmp_path / "data.db"
    conn = store.open_db(db)
    rules = load_all_rules(conn, data_dir=tmp_path)
    local = [r for r in rules if r.source == "local-counterparty"]
    assert len(local) == 1
    assert local[0].match_field == "counterparty"
    assert local[0].priority == DEFAULT_PRIORITY_BY_FIELD["counterparty"]
    assert local[0].pattern == "ACME Corp"
    assert local[0].category == "Робота"


def test_db_rules_loaded(empty_db: Path) -> None:
    conn = store.open_db(empty_db)
    conn.execute(
        "INSERT INTO categorization_rules "
        "(priority, match_field, pattern, category, enabled, created_at, source) "
        "VALUES (50, 'description', 'MyCompany', 'Робота', 1, 0, 'user')"
    )
    rules = load_all_rules(conn, data_dir=empty_db.parent)
    db_rules = [r for r in rules if r.source == "db"]
    assert len(db_rules) == 1
    r = db_rules[0]
    assert r.rule_id is not None
    assert r.priority == 50
    assert r.pattern == "MyCompany"
    # Priority 50 < 100, so it sorts even ahead of seed description rules.
    assert rules[0] is r


def test_match_mcc_exact() -> None:
    rule = Rule(
        priority=300,
        match_field="mcc",
        pattern="5814",
        category="Їжа/Фастфуд",
        source="seed-mcc",
    )
    assert rule.matches(mcc=5814, description=None, counterparty=None) is True
    assert rule.matches(mcc=5812, description=None, counterparty=None) is False
    assert rule.matches(mcc=None, description=None, counterparty=None) is False


def test_match_description_case_insensitive() -> None:
    rule = Rule(
        priority=100,
        match_field="description",
        pattern="(?i)glovo",
        category="Їжа/Доставка",
        source="seed-description",
    )
    assert rule.matches(mcc=None, description="GLOVO UA 042", counterparty=None) is True
    assert rule.matches(mcc=None, description="glovo", counterparty=None) is True
    assert rule.matches(mcc=None, description="uklon", counterparty=None) is False
    assert rule.matches(mcc=None, description=None, counterparty=None) is False


def test_match_counterparty_only() -> None:
    rule = Rule(
        priority=200,
        match_field="counterparty",
        pattern="ACME",
        category="Робота",
        source="local-counterparty",
    )
    assert rule.matches(mcc=None, description="payment", counterparty="ACME Corp") is True
    assert rule.matches(mcc=None, description="ACME Corp", counterparty=None) is False


def test_disabled_rule_does_not_match() -> None:
    rule = Rule(
        priority=100,
        match_field="description",
        pattern="(?i)glovo",
        category="Їжа/Доставка",
        source="db",
        rule_id=1,
        enabled=False,
    )
    assert rule.matches(mcc=None, description="GLOVO UA", counterparty=None) is False


def test_invalid_regex_does_not_crash() -> None:
    """A malformed regex in one rule should return False on match,
    not raise. The whole categorize pass must survive one bad rule."""
    rule = Rule(
        priority=100,
        match_field="description",
        pattern="(unclosed",
        category="X",
        source="db",
        rule_id=1,
    )
    assert rule.matches(mcc=None, description="anything", counterparty=None) is False


def test_first_match_priority_resolution() -> None:
    """Description rule (priority 100) beats MCC rule (priority 300)
    when both would match the same tx."""
    desc = Rule(
        priority=100,
        match_field="description",
        pattern="(?i)glovo",
        category="Їжа/Доставка",
        source="seed-description",
    )
    mcc = Rule(
        priority=300,
        match_field="mcc",
        pattern="5814",
        category="Їжа/Фастфуд",
        source="seed-mcc",
    )
    rules = sorted([mcc, desc], key=lambda r: r.priority)
    winner = first_match(rules, mcc=5814, description="GLOVO UA", counterparty=None)
    assert winner is desc


def test_first_match_returns_none_when_no_match() -> None:
    rule = Rule(
        priority=100,
        match_field="description",
        pattern="(?i)glovo",
        category="X",
        source="seed-description",
    )
    assert first_match([rule], mcc=None, description="ATB", counterparty=None) is None


def test_load_overrides_missing(tmp_path: Path) -> None:
    assert load_overrides(tmp_path) == []


def test_load_overrides_loaded(tmp_path: Path) -> None:
    rules_dir = tmp_path / "rules"
    rules_dir.mkdir()
    (rules_dir / "overrides.local.yaml").write_text(
        "- tx_id: mono_t1\n  category: Подарунки\n  note: Birthday\n"
        "- tx_id: mono_t2\n  category: Робота\n",
        encoding="utf-8",
    )
    rows = load_overrides(tmp_path)
    assert len(rows) == 2
    assert rows[0] == {"tx_id": "mono_t1", "category": "Подарунки", "note": "Birthday"}
    assert rows[1] == {"tx_id": "mono_t2", "category": "Робота", "note": None}


def test_load_overrides_malformed_raises(tmp_path: Path) -> None:
    rules_dir = tmp_path / "rules"
    rules_dir.mkdir()
    (rules_dir / "overrides.local.yaml").write_text(
        "- tx_id: missing_category_field\n",
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="tx_id.*category"):
        load_overrides(tmp_path)
