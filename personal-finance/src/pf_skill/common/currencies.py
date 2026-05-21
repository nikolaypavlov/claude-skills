"""ISO 4217 numeric <-> alpha-3 currency-code helpers.

We persist ``currency_code`` as the ISO 4217 numeric (980 for UAH,
840 for USD, etc.) because that's what Monobank's API returns and what
the cross-plugin contract in ``docs/transactions-schema.md`` mandates.
At the CLI/Claude boundary humans think in alpha codes, so we keep a
small hand-curated map of the currencies we actually see in this
ecosystem (UAH + the dollar/euro/pound triad that Mono lets you hold).

Adding a new code is a one-line change to ``_NUMERIC_TO_ALPHA``. If you
catch yourself reaching for the full ISO table, prefer a third-party
package (``iso4217``) over expanding this map.
"""

from __future__ import annotations

# ISO 4217 numeric -> alpha-3. We curate only currencies that exist in
# the personal-finance ecosystem today; anything else returns ``None``
# from ``alpha_for(...)`` and the CLI keeps the numeric form.
_NUMERIC_TO_ALPHA: dict[int, str] = {
    980: "UAH",
    840: "USD",
    978: "EUR",
    826: "GBP",
}

_ALPHA_TO_NUMERIC: dict[str, int] = {v: k for k, v in _NUMERIC_TO_ALPHA.items()}


def alpha_for(numeric: int) -> str | None:
    """Return the alpha-3 code for an ISO 4217 numeric, or ``None`` for
    a currency we have not seen yet (callers fall back to the numeric)."""
    return _NUMERIC_TO_ALPHA.get(int(numeric))


def numeric_for(alpha: str) -> int | None:
    """Return the ISO 4217 numeric for an alpha-3 code (case insensitive),
    or ``None`` if unknown. Used by CLI flags so ``--currency UAH`` works."""
    return _ALPHA_TO_NUMERIC.get(alpha.upper())


def parse_currency_arg(value: str) -> int:
    """Parse a ``--currency`` CLI value as either ``UAH`` or ``980``.

    Raises ``ValueError`` on anything else so the CLI surface can route
    it to the JSON error contract (``{"ok": false, ...}``) rather than
    silently treating the value as a string filter that matches nothing.
    """
    text = value.strip()
    if not text:
        raise ValueError("empty --currency value")
    if text.isdigit():
        return int(text)
    numeric = numeric_for(text)
    if numeric is None:
        raise ValueError(
            f"unknown currency {value!r}; known alpha codes: "
            f"{sorted(_ALPHA_TO_NUMERIC.keys())}"
        )
    return numeric
