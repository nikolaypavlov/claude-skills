"""Parser unit tests: shape, currency conversion, FX sign handling."""

from __future__ import annotations

from pathlib import Path

from privat24_import.parsers.web_xlsx import parse


def test_parse_returns_one_account(sample_xlsx: Path) -> None:
    statement = parse(sample_xlsx)
    assert statement.account_id.startswith("privat_pan_")
    assert statement.account_currency_code == 980  # UAH
    assert len(statement.rows) == 30  # fixture fixed count


def test_parse_fx_rows_have_signed_op_amount(sample_xlsx: Path) -> None:
    statement = parse(sample_xlsx)
    fx_rows = [r for r in statement.rows if r.op_currency_code is not None]
    assert fx_rows, "fixture seed must include at least one FX row"
    for row in fx_rows:
        # FX is detected by currency mismatch with the account currency.
        assert row.op_currency_code != statement.account_currency_code
        assert row.op_amount_minor is not None
        # Sign of op_amount_minor must mirror amount_minor so the
        # "negative = outflow" convention holds for both columns.
        assert (row.amount_minor < 0) == (
            row.op_amount_minor < 0
        ) or row.amount_minor == 0


def test_parse_domestic_rows_have_null_op_columns(sample_xlsx: Path) -> None:
    statement = parse(sample_xlsx)
    domestic = [r for r in statement.rows if r.op_currency_code is None]
    assert domestic, "fixture seed must include some non-FX rows"
    for row in domestic:
        assert row.op_amount_minor is None
        assert row.op_currency_code is None


def test_parse_amounts_are_minor_units(sample_xlsx: Path) -> None:
    statement = parse(sample_xlsx)
    # Every amount should be a non-zero integer (rounded to minor units).
    for row in statement.rows:
        assert isinstance(row.amount_minor, int)
        assert abs(row.amount_minor) >= 50  # fixture floor of 0.50 UAH
