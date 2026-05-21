"""Dedup tests: natural-key hashing + twin-row counter."""

from __future__ import annotations

from privat24_import.core.dedup import assign_ids


def test_same_natural_key_collides_across_inputs() -> None:
    """Re-importing the same logical row from different files must NOT
    duplicate. The hash depends ONLY on (ts, amount, description, acc)."""
    row = {
        "ts": 1_700_000_000,
        "amount_minor": -5000,
        "description": "x",
        "account_id": "a",
    }
    id1 = assign_ids([row])[0]
    id2 = assign_ids([row])[0]
    assert id1 == id2
    assert id1.startswith("privat_h_")
    assert len(id1) == len("privat_h_") + 16


def test_twin_rows_get_distinct_ids() -> None:
    """Two rows with identical (ts, amount, description, account_id) -
    e.g. an auto-payment that executes twice in the same second - must
    still get distinct ids via the within-group counter."""
    twin = {
        "ts": 1_700_000_000,
        "amount_minor": -100,
        "description": "twin",
        "account_id": "a",
    }
    ids = assign_ids([twin, twin, twin])
    assert len(set(ids)) == 3, f"expected 3 distinct ids, got {ids}"


def test_twin_counter_is_stable_across_independent_calls() -> None:
    """Counter resets per call, so the same twin sequence yields the
    same id list every time. This is what makes overlapping re-exports
    of files containing twin transactions dedupe correctly."""
    twin = {
        "ts": 1_700_000_000,
        "amount_minor": -100,
        "description": "twin",
        "account_id": "a",
    }
    ids1 = assign_ids([twin, twin])
    ids2 = assign_ids([twin, twin])
    assert ids1 == ids2


def test_unrelated_rows_have_distinct_ids() -> None:
    rows = [
        {"ts": 1, "amount_minor": -1, "description": "a", "account_id": "x"},
        {"ts": 2, "amount_minor": -1, "description": "a", "account_id": "x"},
        {"ts": 1, "amount_minor": -2, "description": "a", "account_id": "x"},
        {"ts": 1, "amount_minor": -1, "description": "b", "account_id": "x"},
        {"ts": 1, "amount_minor": -1, "description": "a", "account_id": "y"},
    ]
    ids = assign_ids(rows)
    assert len(set(ids)) == 5
