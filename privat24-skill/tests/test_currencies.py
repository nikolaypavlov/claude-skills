"""ISO 4217 lookup: known codes, case-insensitivity, unknown rejection."""

from __future__ import annotations

import pytest

from privat24_import.core.currencies import UnknownCurrency, to_numeric


def test_known_codes_round_trip_to_numeric() -> None:
    assert to_numeric("UAH") == 980
    assert to_numeric("USD") == 840
    assert to_numeric("EUR") == 978


def test_case_insensitive() -> None:
    assert to_numeric("uah") == 980
    assert to_numeric("uSd") == 840


def test_strips_whitespace() -> None:
    assert to_numeric("  UAH  ") == 980


def test_unknown_raises() -> None:
    with pytest.raises(UnknownCurrency):
        to_numeric("XYZ")


def test_empty_raises() -> None:
    with pytest.raises(UnknownCurrency):
        to_numeric("")
