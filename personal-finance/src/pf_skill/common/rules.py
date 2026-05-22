"""Categorization rule loading and matching.

Four rule sources merge into a single priority-sorted list at every
``apply_rules`` call (and at every ``pf-rules list`` invocation, so the
SKILL.md "Claude proposes a rule, user yeses, retroactive apply" flow
sees the new rule immediately without a reload step):

| Source                                              | match_field   | default priority | rule_id |
|-----------------------------------------------------|---------------|------------------|---------|
| ``pf_skill/rules/description.yaml`` (seed)          | description   | 100              | None    |
| ``$DATA_DIR/rules/counterparty.local.yaml`` (user)  | counterparty  | 200              | None    |
| ``pf_skill/rules/mcc.json`` (seed)                  | mcc           | 300              | None    |
| ``categorization_rules`` table (user, via pf-rules) | row value     | row value        | row id  |

Lower priority wins; ties broken by source order then pattern string so
the order is deterministic between invocations. The two seed files are
loaded via ``importlib.resources`` so they travel with the installed
wheel; the local YAML lives outside the repo (gitignored) and is
optional - a missing file is silently fine.

Per-tx pins (``overrides.local.yaml``) are NOT rules - they are
UPSERTed into ``category_overrides`` by the categorizer. See
``categorizer.py``.
"""

from __future__ import annotations

import json
import re
import sqlite3
from collections.abc import Iterable
from dataclasses import dataclass
from importlib import resources
from pathlib import Path
from typing import Any

import yaml

from .store import default_db_path

# Single source of truth for default rule priorities. Used by every
# seed/local loader to stamp imported rules, and by ``cmd_add`` /
# ``preview_rule`` to pick a default when the user doesn't pass
# ``--priority`` explicitly. Lower number = checked first; description
# rules outrank counterparty rules which outrank MCC fallback.
DEFAULT_PRIORITY_BY_FIELD: dict[str, int] = {
    "description": 100,
    "counterparty": 200,
    "mcc": 300,
}

# Valid ``match_field`` values - keep in sync with the
# ``categorization_rules.match_field`` column constraints documented in
# the SQL schema. Used to validate rule rows from every source.
VALID_MATCH_FIELDS: tuple[str, ...] = tuple(DEFAULT_PRIORITY_BY_FIELD.keys())


@dataclass(frozen=True)
class Rule:
    """A single categorization rule, drawn from any of the four sources.

    ``rule_id`` is the ``categorization_rules.id`` for DB-sourced rules
    (used as the soft FK in ``tx_category.rule_id``). For seed and
    local-YAML rules it is ``None`` and the categorizer stores ``None``
    in ``tx_category.rule_id`` plus ``set_by='rule'`` so a future
    inspector can tell "rule-matched" from "manual".
    """

    priority: int
    match_field: str
    pattern: str
    category: str
    source: str
    rule_id: int | None = None
    enabled: bool = True

    def matches(
        self, *, mcc: int | None, description: str | None, counterparty: str | None
    ) -> bool:
        """Test the rule against the three searchable fields of a tx row."""
        if not self.enabled:
            return False
        if self.match_field == "mcc":
            return mcc is not None and str(mcc) == self.pattern
        haystack = description if self.match_field == "description" else counterparty
        if haystack is None:
            return False
        try:
            return re.search(self.pattern, haystack) is not None
        except re.error:
            # Invalid regex - treat as non-match rather than crashing the
            # whole categorize pass. The malformed rule is surfaced by
            # ``pf-rules list``; this branch keeps a typo in one rule
            # from blocking categorization for every other rule.
            return False


def load_all_rules(
    conn: sqlite3.Connection,
    *,
    data_dir: Path | None = None,
) -> list[Rule]:
    """Aggregate all rule sources into one priority-sorted list.

    ``data_dir`` defaults to the parent of ``default_db_path()`` (so
    ``~/finances/rules/counterparty.local.yaml`` works out of the box);
    pass an explicit dir from tests.
    """
    if data_dir is None:
        data_dir = default_db_path().parent
    rules: list[Rule] = []
    rules.extend(_load_seed_descriptions())
    rules.extend(_load_seed_mcc())
    rules.extend(_load_local_counterparty(data_dir))
    rules.extend(_load_db_rules(conn))
    return sorted(rules, key=_rule_sort_key)


def first_match(
    rules: Iterable[Rule],
    *,
    mcc: int | None,
    description: str | None,
    counterparty: str | None,
) -> Rule | None:
    """Return the first rule whose ``matches`` predicate succeeds.

    ``rules`` must already be priority-sorted (use ``load_all_rules``).
    Returns ``None`` if no rule matches - the categorizer leaves the row
    uncategorized and surfaces it in the report.
    """
    for rule in rules:
        if rule.matches(mcc=mcc, description=description, counterparty=counterparty):
            return rule
    return None


def load_overrides(data_dir: Path | None = None) -> list[dict[str, Any]]:
    """Load ``$DATA_DIR/rules/overrides.local.yaml``.

    Returns a list of ``{tx_id, category, note?}`` dicts. Missing file
    returns ``[]`` - the local YAML is optional and never required.

    Raises ``ValueError`` if the YAML is malformed (so the categorizer
    surfaces the issue as a CliError rather than silently dropping
    overrides).
    """
    if data_dir is None:
        data_dir = default_db_path().parent
    path = data_dir / "rules" / "overrides.local.yaml"
    if not path.is_file():
        return []
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    if raw is None:
        return []
    if not isinstance(raw, list):
        raise ValueError(f"{path}: expected a YAML list of overrides, got {type(raw).__name__}")
    out: list[dict[str, Any]] = []
    for i, entry in enumerate(raw):
        if not isinstance(entry, dict) or "tx_id" not in entry or "category" not in entry:
            raise ValueError(f"{path}[{i}]: each override needs 'tx_id' and 'category' fields")
        out.append(
            {
                "tx_id": str(entry["tx_id"]),
                "category": str(entry["category"]),
                "note": entry.get("note"),
            }
        )
    return out


# --- private loaders ---------------------------------------------------------


def _load_seed_descriptions() -> list[Rule]:
    raw = _read_packaged_yaml("description.yaml")
    if raw is None:
        return []
    if not isinstance(raw, list):
        raise ValueError(
            "pf_skill/rules/description.yaml: expected a YAML list of "
            f"{{pattern, category}} dicts, got {type(raw).__name__}"
        )
    rules: list[Rule] = []
    for i, entry in enumerate(raw):
        rules.append(
            _yaml_entry_to_rule(
                entry,
                index=i,
                match_field="description",
                priority=DEFAULT_PRIORITY_BY_FIELD["description"],
                source="seed-description",
                location="pf_skill/rules/description.yaml",
            )
        )
    return rules


def _load_seed_mcc() -> list[Rule]:
    text = resources.files("pf_skill.rules").joinpath("mcc.json").read_text(encoding="utf-8")
    raw = json.loads(text)
    if not isinstance(raw, dict):
        raise ValueError(
            f"pf_skill/rules/mcc.json: expected a JSON object, got {type(raw).__name__}"
        )
    rules: list[Rule] = []
    for mcc_key, category in raw.items():
        if mcc_key.startswith("_"):
            # Allow JSON-comment-like keys ("_comment") without polluting
            # the rule list.
            continue
        if not mcc_key.isdigit():
            raise ValueError(
                f"pf_skill/rules/mcc.json: key {mcc_key!r} is not a numeric MCC string"
            )
        rules.append(
            Rule(
                priority=DEFAULT_PRIORITY_BY_FIELD["mcc"],
                match_field="mcc",
                pattern=mcc_key,
                category=str(category),
                source="seed-mcc",
            )
        )
    return rules


def _load_local_counterparty(data_dir: Path) -> list[Rule]:
    path = data_dir / "rules" / "counterparty.local.yaml"
    if not path.is_file():
        return []
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    if raw is None:
        return []
    if not isinstance(raw, list):
        raise ValueError(
            f"{path}: expected a YAML list of {{pattern, category}} dicts, got {type(raw).__name__}"
        )
    rules: list[Rule] = []
    for i, entry in enumerate(raw):
        rules.append(
            _yaml_entry_to_rule(
                entry,
                index=i,
                match_field="counterparty",
                priority=DEFAULT_PRIORITY_BY_FIELD["counterparty"],
                source="local-counterparty",
                location=str(path),
            )
        )
    return rules


def _load_db_rules(conn: sqlite3.Connection) -> list[Rule]:
    rows = conn.execute(
        "SELECT id, priority, match_field, pattern, category, enabled FROM categorization_rules"
    ).fetchall()
    rules: list[Rule] = []
    for r in rows:
        match_field = str(r[2])
        if match_field not in VALID_MATCH_FIELDS:
            # Don't crash the whole pass; skip the malformed row. pf-rules
            # list will reflect it for the user to clean up.
            continue
        rules.append(
            Rule(
                priority=int(r[1]),
                match_field=match_field,
                pattern=str(r[3]),
                category=str(r[4]),
                source="db",
                rule_id=int(r[0]),
                enabled=bool(r[5]),
            )
        )
    return rules


# --- helpers ----------------------------------------------------------------


def _yaml_entry_to_rule(
    entry: Any,
    *,
    index: int,
    match_field: str,
    priority: int,
    source: str,
    location: str,
) -> Rule:
    if not isinstance(entry, dict) or "pattern" not in entry or "category" not in entry:
        raise ValueError(f"{location}[{index}]: each rule needs 'pattern' and 'category' fields")
    return Rule(
        priority=int(entry.get("priority", priority)),
        match_field=match_field,
        pattern=str(entry["pattern"]),
        category=str(entry["category"]),
        source=source,
    )


def _read_packaged_yaml(filename: str) -> Any:
    text = resources.files("pf_skill.rules").joinpath(filename).read_text(encoding="utf-8")
    return yaml.safe_load(text)


def _rule_sort_key(rule: Rule) -> tuple[int, str, str]:
    """Deterministic ordering: priority asc, then source order, then
    pattern. Tie-break on source so DB rules (priority value already set
    by the user) sort cleanly alongside seed rules at the same priority.
    """
    return (rule.priority, rule.source, rule.pattern)
