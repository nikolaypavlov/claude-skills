"""Parser unit tests: shape, currency conversion, FX sign handling,
multi-card rejection, timezone conversion."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest
from openpyxl import Workbook

from privat24_import.parsers.detect import WEB_XLSX_HEADERS
from privat24_import.parsers.web_xlsx import KYIV_TZ, parse


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
        if row.amount_minor == 0:
            # Zero account amount: op amount must also be 0 (no sign to
            # mirror). The escape clause is tested by
            # ``test_fx_zero_amount_gives_zero_op_amount`` separately.
            assert row.op_amount_minor == 0
        else:
            # Sign of op_amount_minor must mirror amount_minor so the
            # "negative = outflow" convention holds for both columns.
            assert (row.amount_minor < 0) == (row.op_amount_minor < 0)


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


def _make_xlsx(tmp_path: Path, body: list[tuple], *, name: str = "case.xlsx") -> Path:
    wb = Workbook()
    ws = wb.active
    assert ws is not None
    ws.title = "Виписки"
    ws.append(["Історія операцій за період"] + [""] * 9)
    ws.append(list(WEB_XLSX_HEADERS))
    for row in body:
        ws.append(row)
    out = tmp_path / name
    wb.save(out)
    return out


def test_parse_rejects_multi_card_xlsx(tmp_path: Path) -> None:
    """`web_xlsx.parse` raises when the export contains more than one
    masked PAN, since each PAN maps to a distinct account_id."""
    body = [
        (
            "20.05.2026 09:00:00",
            "Магазини",
            "5168 **** **** 1111",
            "SHOP A",
            -100.0,
            "UAH",
            100.0,
            "UAH",
            1000.0,
            "UAH",
        ),
        (
            "20.05.2026 09:30:00",
            "Магазини",
            "5168 **** **** 2222",
            "SHOP B",
            -50.0,
            "UAH",
            50.0,
            "UAH",
            950.0,
            "UAH",
        ),
    ]
    out = _make_xlsx(tmp_path, body, name="multi-card.xlsx")
    with pytest.raises(ValueError, match="one card"):
        parse(out)


def test_parse_handles_kyiv_local_time(tmp_path: Path) -> None:
    """Naive timestamps in the export are Kyiv local; the parser must
    attach Europe/Kyiv before computing the UTC unix timestamp. We feed
    a single mid-summer row (DST in effect, +3h offset) and assert the
    resulting ts equals the same wall clock interpreted in Kyiv tz -
    NOT what we'd get by treating the cell as UTC directly (the bug
    flagged in PR #8 review)."""
    wall = datetime(2026, 7, 15, 14, 30, 0)
    body = [
        (
            wall.strftime("%d.%m.%Y %H:%M:%S"),
            "Магазини",
            "5168 **** **** 3333",
            "midsummer",
            -10.0,
            "UAH",
            10.0,
            "UAH",
            990.0,
            "UAH",
        ),
    ]
    out = _make_xlsx(tmp_path, body, name="tz.xlsx")
    statement = parse(out)
    assert len(statement.rows) == 1
    expected = int(wall.replace(tzinfo=ZoneInfo("Europe/Kyiv")).timestamp())
    assert statement.rows[0].ts == expected
    # The fix must produce a different value than the old "treat as UTC"
    # behaviour - confirms the regression-guard.
    naive_as_utc = int(wall.replace(tzinfo=ZoneInfo("UTC")).timestamp())
    assert statement.rows[0].ts != naive_as_utc
    # And KYIV_TZ should be the proper zoneinfo, not a placeholder UTC.
    assert getattr(KYIV_TZ, "key", "") == "Europe/Kyiv"


def test_fx_zero_amount_gives_zero_op_amount(tmp_path: Path) -> None:
    """A reversed / commission-free FX transaction can leave the
    account-side amount at exactly zero. The op amount must also be 0
    so the column pair stays internally consistent. Before the fix, the
    sign branch would assign +1 and store a positive op_amount."""
    body = [
        (
            "20.05.2026 09:00:00",
            "Перекази",
            "5168 **** **** 4444",
            "free FX",
            0.0,
            "UAH",
            120.0,
            "USD",
            1000.0,
            "UAH",
        ),
    ]
    out = _make_xlsx(tmp_path, body, name="zero-fx.xlsx")
    statement = parse(out)
    assert len(statement.rows) == 1
    row = statement.rows[0]
    assert row.amount_minor == 0
    assert row.op_amount_minor == 0
    assert row.op_currency_code == 840  # USD
