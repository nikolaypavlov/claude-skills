"""ISO 4217 currency code lookup.

Privat24 XLSX exports use 3-letter alpha codes (UAH, USD, EUR). The shared
schema convention stores numeric codes (980, 840, 978). This module is the
single source of truth for the mapping.
"""

# Minimal set covering Privat24 user reality. Extend as needed; unknown
# codes raise ``UnknownCurrency`` so silent NULLs don't pollute the data.
ALPHA_TO_NUMERIC: dict[str, int] = {
    "UAH": 980,
    "USD": 840,
    "EUR": 978,
    "GBP": 826,
    "PLN": 985,
    "CZK": 203,
    "TRY": 949,
    "JPY": 392,
    "CHF": 756,
    "CAD": 124,
}


class UnknownCurrency(ValueError):
    """Raised when a currency alpha code is not in the lookup table."""


def to_numeric(alpha: str) -> int:
    """Convert a 3-letter alpha code (case-insensitive) to ISO 4217 numeric."""
    if not alpha:
        raise UnknownCurrency("empty currency code")
    key = alpha.strip().upper()
    if key not in ALPHA_TO_NUMERIC:
        raise UnknownCurrency(
            f"unknown currency code '{alpha}' "
            f"(extend privat24_import.core.currencies.ALPHA_TO_NUMERIC if legitimate)"
        )
    return ALPHA_TO_NUMERIC[key]
