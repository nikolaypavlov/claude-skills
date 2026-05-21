"""Generate a synthetic Privat24 XLSX statement for tests.

Output mirrors the privat24.ua web export shape exactly (title row,
header row, 10 data columns). All merchants, account numbers, and
descriptions come from a fixed seeded RNG so the file is byte-stable
across regenerations - the committed ``sample_web.xlsx`` next to this
script is the canonical reference for tests.

Run::

    uv run python fixtures/generate.py

NEVER edit the produced XLSX by hand. Regenerate via this script so the
content stays reproducible.
"""

from __future__ import annotations

import random
from datetime import datetime, timedelta
from decimal import Decimal
from pathlib import Path

from openpyxl import Workbook  # type: ignore[import-not-found]

# Synthetic, generic merchant names. No real brands.
MERCHANTS_UAH = [
    ("Аптеки", "APTEKA TEST, KYIV"),
    ("Кафе та ресторани", "CAFE TEST, KYIV"),
    ("Магазини", "SHOP TEST 1, KYIV"),
    ("Магазини", "SHOP TEST 2, KHARKIV"),
    ("Транспорт", "TRANSPORT TEST"),
    ("Зарахування переказу", "Test sender alpha"),
    ("Перекази", "Test recipient beta"),
    ("Комуналка та Інтернет", "TEST UTILITY"),
    ("Фонди та організації", "Автоплатіж. Отримувач Тестовий фонд. Коментар: внесок"),
]

# A handful of FX rows (account UAH, txn USD/EUR) to exercise the FX
# branch. The zero-amount entry covers the "commission reversal /
# free conversion" edge case where the account side nets out exactly to
# zero - the parser must store ``op_amount_minor = 0`` rather than
# defaulting to a positive sign.
FX_ROWS = [
    (
        "Магазини",
        "SHOP TEST USD",
        -50_00,
        "USD",
        -1_50_00,
    ),  # -USD 1.50 charged as -UAH 50.00
    ("Перекази", "EUR transfer test", -200_00, "EUR", -5_00_00),
    ("Сервіси", "FREE FX TEST", 0, "USD", 1_00_00),  # zero-amount FX
]

TITLE_FMT = "Історія операцій за період {start} - {end}"
HEADERS = (
    "Дата",
    "Категорія",
    "Картка",
    "Опис операції",
    "Сума в валюті картки",
    "Валюта картки",
    "Сума в валюті транзакції",
    "Валюта транзакції",
    "Залишок на кінець періоду",
    "Валюта залишку",
)

DEFAULT_CARD = "4441 **** **** 0007"
DEFAULT_SEED = 42


def generate(out_path: Path, *, seed: int = DEFAULT_SEED, rows: int = 30) -> Path:
    """Write a synthetic XLSX. Returns the output path."""
    if rows < len(FX_ROWS):
        raise ValueError(
            f"need at least {len(FX_ROWS)} rows to cover all FX_ROWS, got rows={rows}"
        )
    rng = random.Random(seed)
    wb = Workbook()
    ws = wb.active
    assert ws is not None
    ws.title = "Виписки"

    # Build deterministic timestamps from a fixed anchor so the file is
    # byte-stable across regenerations.
    end = datetime(2026, 5, 20, 9, 0, 0)
    start = end - timedelta(days=20)
    ws.append(
        [
            TITLE_FMT.format(
                start=start.strftime("%d.%m.%Y"), end=end.strftime("%d.%m.%Y")
            ),
            *([""] * 9),
        ]
    )
    ws.append(list(HEADERS))

    balance = Decimal("10000.00")
    cur_ts = start
    body: list[tuple] = []
    # Mix domestic and FX rows. The shuffled plan ensures FX rows can
    # land anywhere in the timeline, not just at the end.
    plan = ["DOM"] * (rows - len(FX_ROWS)) + ["FX"] * len(FX_ROWS)
    rng.shuffle(plan)
    fx_iter = iter(FX_ROWS)
    for kind in plan:
        cur_ts = cur_ts + timedelta(minutes=rng.randint(15, 1440))
        if kind == "DOM":
            category, desc = rng.choice(MERCHANTS_UAH)
            # Skew toward outflow (negative) but allow some inflows.
            sign = -1 if rng.random() < 0.8 else 1
            amount_uah = Decimal(rng.randint(50, 200000)) / Decimal(100) * sign
            op_amount_for_file = float(abs(amount_uah))
            op_ccy = "UAH"
        else:
            category, desc, amount_uah_minor, op_ccy, op_amount_uah_minor = next(
                fx_iter
            )
            amount_uah = Decimal(amount_uah_minor) / Decimal(100)
            # op_amount is the *positive* op-currency amount (per Privat24
            # source convention); we encode an unsigned absolute amount in
            # the file. Use a small fixed conversion - we just need the
            # numbers to be self-consistent.
            op_amount_for_file = float(
                abs(Decimal(op_amount_uah_minor) / Decimal(100) / Decimal(35)).quantize(
                    Decimal("0.01")
                )
            )
        balance = balance + amount_uah
        body.append(
            (
                cur_ts.strftime("%d.%m.%Y %H:%M:%S"),
                category,
                DEFAULT_CARD,
                desc,
                float(amount_uah),
                "UAH",
                op_amount_for_file,
                op_ccy,
                float(balance),
                "UAH",
            )
        )

    # Privat24 sorts newest first.
    body.sort(key=lambda r: r[0], reverse=True)
    for row in body:
        ws.append(row)

    out_path.parent.mkdir(parents=True, exist_ok=True)
    wb.save(out_path)
    return out_path


if __name__ == "__main__":
    out = Path(__file__).parent / "sample_web.xlsx"
    print(f"writing {out}")
    generate(out)
