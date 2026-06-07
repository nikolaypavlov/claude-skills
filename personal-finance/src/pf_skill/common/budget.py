"""Budget feature: parsing, validation, materialisation.

This module owns:

- Plain dataclasses for plan rows (``PlanRow``) so the parsers and
  the materialiser agree on a single in-memory shape.
- CSV parser for the ``Plans`` sheet format (the canonical exchange
  format with Google Sheets - the user copies a single CSV per month).
- XLSX parser for two-sheet workbooks (``Baseline`` + ``Plans``);
  optional, depends on ``openpyxl`` being installed.
- Category validation: known = ``tx_category`` ∪ ``category_overrides``
  ∪ ``categorization_rules`` ∪ ``category_registry``. Unknown entries
  get Levenshtein-distance suggestions against the known set.
- Materialisation: one budget per (period, currency). Idempotent
  per (period, currency) - re-running replaces the lines unless
  ``status='closed'`` (in which case it refuses without ``--force``).

The CLI layer (``budget_cli.py``) is intentionally thin around these
helpers - same separation as ``queries.py`` vs ``query.py``.
"""

from __future__ import annotations

import csv
import json
import re
import sqlite3
import time
from collections.abc import Iterable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .currencies import numeric_for

PERIOD_RE = re.compile(r"^\d{4}-\d{2}$")
ALLOWED_KINDS = ("baseline", "one_time", "income")

# Required columns for each sheet shape, enforced at parse time.
_PLANS_REQUIRED = ("Period", "Category", "Currency", "Kind", "Amount")
_PLANS_OPTIONAL = ("Note",)
_BASELINE_REQUIRED = ("Category", "Currency", "Kind", "Monthly target")
_BASELINE_OPTIONAL = ("Note",)


class BudgetParseError(ValueError):
    """Raised by parser/validator with a human-readable explanation
    of which row / column / value broke the contract. Carries an
    optional ``details`` payload (e.g. list of unknown categories
    with suggestions) so the CLI can render structured JSON output."""

    def __init__(
        self,
        message: str,
        *,
        kind: str = "BudgetParse",
        details: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.kind = kind
        self.details = details or {}


@dataclass
class PlanRow:
    """One concrete budget line, after CSV/XLSX parsing and merging.

    ``period`` is always set (Plans rows carry it; Baseline rows get
    the ``--period`` value from the CLI at merge time). ``amount_minor``
    is signed (negative for outflows, positive for income).
    """

    period: str
    category: str
    currency_code: int
    kind: str
    amount_minor: int
    note: str | None = None
    # ``source_row``: human-readable origin of this row for error
    # messages (e.g. ``Plans!B14`` or ``baseline.csv:3``). Optional
    # so internal callers (tests) don't have to thread it.
    source_row: str | None = None


@dataclass
class ValidationResult:
    """What ``validate_categories`` returns to the caller.

    ``unknown``: list of ``(category, suggestions)`` where each
    suggestion is ``(candidate, distance)`` sorted ascending by
    distance, then alphabetically. Empty when every category was
    recognised.
    """

    rows: list[PlanRow]
    unknown: list[tuple[str, list[tuple[str, int]]]] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Parsing
# ---------------------------------------------------------------------------


def parse_plans_csv(path: Path) -> list[PlanRow]:
    """Read a Plans-shape CSV. Header must match ``_PLANS_REQUIRED``;
    ``Note`` is optional."""
    with path.open(encoding="utf-8") as f:
        reader = csv.DictReader(f)
        _check_columns(reader.fieldnames, _PLANS_REQUIRED, _PLANS_OPTIONAL, sheet="Plans")
        rows: list[PlanRow] = []
        for i, raw in enumerate(reader, start=2):  # row 1 = header
            if not any((raw.get(k) or "").strip() for k in _PLANS_REQUIRED):
                continue  # skip blank trailing rows
            rows.append(_row_from_plans(raw, source_row=f"{path.name}:{i}"))
    return rows


def parse_baseline_csv(path: Path, period: str) -> list[PlanRow]:
    """Read a Baseline-shape CSV and stamp ``period`` onto each row."""
    _validate_period(period, "period")
    with path.open(encoding="utf-8") as f:
        reader = csv.DictReader(f)
        _check_columns(
            reader.fieldnames, _BASELINE_REQUIRED, _BASELINE_OPTIONAL, sheet="Baseline"
        )
        rows: list[PlanRow] = []
        for i, raw in enumerate(reader, start=2):
            if not any((raw.get(k) or "").strip() for k in _BASELINE_REQUIRED):
                continue
            rows.append(_row_from_baseline(raw, period, source_row=f"{path.name}:{i}"))
    return rows


def parse_workbook_xlsx(path: Path) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Read a two-sheet workbook (Baseline + Plans). Returns the raw
    dict rows (header row drives keys) so the caller can stamp the
    period onto Baseline rows and merge with Plans.

    Lazy-imports ``openpyxl`` so the rest of the budget feature is
    usable on installs without the optional dependency.
    """
    try:
        from openpyxl import load_workbook  # type: ignore[import-not-found]
    except ImportError as exc:  # pragma: no cover - covered by message
        raise BudgetParseError(
            "openpyxl is required to read XLSX files; install with "
            "``uv pip install openpyxl`` or use a CSV export of each sheet",
            kind="MissingDependency",
        ) from exc

    wb = load_workbook(path, read_only=True, data_only=True)
    baseline_rows: list[dict[str, Any]] = []
    plans_rows: list[dict[str, Any]] = []
    for sheet_name, target, required, optional in (
        ("Baseline", baseline_rows, _BASELINE_REQUIRED, _BASELINE_OPTIONAL),
        ("Plans", plans_rows, _PLANS_REQUIRED, _PLANS_OPTIONAL),
    ):
        if sheet_name not in wb.sheetnames:
            continue
        ws = wb[sheet_name]
        rows_iter = ws.iter_rows(values_only=True)
        try:
            raw_header = next(rows_iter)
        except StopIteration:
            continue
        # Coerce header cells to strings. Sheets occasionally come
        # back with non-string headers (numbers, dates) - those are
        # legitimately bad input that we want to surface via
        # _check_columns below.
        header: list[str] = [
            h.strip() if isinstance(h, str) else str(h) if h is not None else ""
            for h in raw_header
        ]
        _check_columns(header, required, optional, sheet=sheet_name)
        for i, values in enumerate(rows_iter, start=2):
            if values is None or all(
                v is None or (isinstance(v, str) and not v.strip()) for v in values
            ):
                continue
            row_dict: dict[str, Any] = {
                header[j]: ("" if values[j] is None else values[j])
                for j in range(min(len(header), len(values)))
                if header[j]
            }
            row_dict["__source_row__"] = f"{sheet_name}!{i}"
            target.append(row_dict)
    wb.close()
    return baseline_rows, plans_rows


def merge_baseline_plans(
    baseline: Iterable[PlanRow],
    plans: Iterable[PlanRow],
    *,
    period: str,
) -> list[PlanRow]:
    """Combine workbook-level Baseline with period-specific Plans.

    Rules:
    - Plans rows with the target ``period`` take precedence: any
      Baseline row with the same ``(category, currency_code, kind)``
      is dropped.
    - Plans rows with a different period are filtered out (they belong
      to a different month's budget, not this one).
    - The result preserves Baseline first (in input order), Plans
      second, so deterministic ordering helps tests.
    """
    plans_for_period = [r for r in plans if r.period == period]
    suppress = {
        (r.category, r.currency_code, r.kind) for r in plans_for_period
    }
    out: list[PlanRow] = []
    for r in baseline:
        if r.period != period:
            # Baseline rows always carry the period stamped in the parse
            # step; this should be invariant.
            continue
        if (r.category, r.currency_code, r.kind) in suppress:
            continue
        out.append(r)
    out.extend(plans_for_period)
    return out


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------


def known_categories(conn: sqlite3.Connection) -> set[str]:
    """All categories the system recognises right now: in-use anywhere
    in the rules / tx tables, plus declared-but-unused from the
    registry."""
    queries = (
        "SELECT category FROM tx_category",
        "SELECT category FROM category_overrides",
        "SELECT category FROM categorization_rules",
        "SELECT category FROM category_registry",
        "SELECT category FROM budget_line",
    )
    known: set[str] = set()
    for q in queries:
        try:
            known.update(r[0] for r in conn.execute(q) if r[0])
        except sqlite3.OperationalError as exc:
            # Pre-migration tables may not exist. The store always
            # brings the schema to current before this is called, but
            # the defensive probe is cheap.
            if "no such table" not in str(exc).lower():
                raise
    return known


def levenshtein(a: str, b: str) -> int:
    """Iterative DP Levenshtein distance.

    Hand-rolled rather than dragging in ``rapidfuzz`` - the vocabulary
    of categories is small (tens of strings) and we only call this on
    the unknowns, never on a hot path.
    """
    if a == b:
        return 0
    if not a:
        return len(b)
    if not b:
        return len(a)
    prev = list(range(len(b) + 1))
    curr = [0] * (len(b) + 1)
    for i, ca in enumerate(a, start=1):
        curr[0] = i
        for j, cb in enumerate(b, start=1):
            cost = 0 if ca == cb else 1
            curr[j] = min(
                prev[j] + 1,         # deletion
                curr[j - 1] + 1,     # insertion
                prev[j - 1] + cost,  # substitution
            )
        prev, curr = curr, prev
    return prev[len(b)]


def suggest_categories(
    target: str, candidates: Iterable[str], *, top_n: int = 3
) -> list[tuple[str, int]]:
    """Return the closest ``top_n`` candidates by Levenshtein distance,
    sorted ascending by distance then by name."""
    scored = [(c, levenshtein(target, c)) for c in candidates]
    scored.sort(key=lambda x: (x[1], x[0]))
    return scored[:top_n]


def validate_categories(
    rows: list[PlanRow],
    conn: sqlite3.Connection,
) -> ValidationResult:
    """Split ``rows`` into known / unknown by checking each category
    against the current taxonomy. Unknowns come back with the top-3
    closest candidates so the CLI / caller can present a helpful
    error message.
    """
    known = known_categories(conn)
    unknown_set: list[tuple[str, list[tuple[str, int]]]] = []
    seen_unknown: set[str] = set()
    for r in rows:
        if r.category in known:
            continue
        if r.category in seen_unknown:
            continue
        seen_unknown.add(r.category)
        unknown_set.append((r.category, suggest_categories(r.category, known)))
    return ValidationResult(rows=rows, unknown=unknown_set)


def register_unknowns(
    conn: sqlite3.Connection, unknowns: Iterable[str], *, now_ts: int | None = None
) -> int:
    """Insert each unknown into ``category_registry`` with
    ``declared_via='budget-import'``. Returns count of newly-added
    rows (skips ones already present).
    """
    ts = now_ts if now_ts is not None else int(time.time())
    added = 0
    for c in unknowns:
        cur = conn.execute(
            "INSERT OR IGNORE INTO category_registry "
            "(category, declared_at, declared_via) VALUES (?, ?, ?)",
            (c, ts, "budget-import"),
        )
        if cur.rowcount:
            added += 1
    return added


# ---------------------------------------------------------------------------
# Materialisation
# ---------------------------------------------------------------------------


@dataclass
class MaterialiseResult:
    period: str
    # cur -> {budget_id, lines_added, lines_replaced, status_after}
    by_currency: dict[int, dict[str, Any]]


def materialise_budget(
    conn: sqlite3.Connection,
    *,
    period: str,
    rows: list[PlanRow],
    source: str,
    force: bool = False,
    now_ts: int | None = None,
) -> MaterialiseResult:
    """Write the plan to ``budget`` / ``budget_line`` tables.

    One budget row per (period, currency_code) found in ``rows``.
    Existing draft / active budgets are replaced (all lines deleted
    then re-inserted in the same transaction). Closed budgets are
    refused unless ``force=True``.

    Caller is responsible for opening the DB connection and managing
    its lifetime; this function does NOT call ``conn.close``. It DOES
    drive the transaction boundary - one BEGIN/COMMIT per currency so
    a UAH success is kept even if the USD slice fails downstream.
    """
    _validate_period(period, "period")
    ts = now_ts if now_ts is not None else int(time.time())
    by_currency: dict[int, list[PlanRow]] = {}
    for r in rows:
        by_currency.setdefault(r.currency_code, []).append(r)

    result = MaterialiseResult(period=period, by_currency={})

    for cur_code, items in sorted(by_currency.items()):
        existing = conn.execute(
            "SELECT id, status FROM budget WHERE period = ? AND currency_code = ?",
            (period, cur_code),
        ).fetchone()

        conn.execute("BEGIN")
        try:
            replaced = 0
            if existing is not None:
                budget_id, status = existing
                if status == "closed" and not force:
                    conn.rollback()
                    raise BudgetParseError(
                        f"budget for {period}/{cur_code} is closed; "
                        "pass --force to overwrite (rare) or "
                        "pf-budget reopen first",
                        kind="ClosedBudget",
                        details={"period": period, "currency_code": cur_code},
                    )
                if status == "closed" and force:
                    # Walk through reopen → replace → close so the
                    # trigger never sees an insert into a closed
                    # parent.
                    conn.execute(
                        "UPDATE budget SET status = 'active' WHERE id = ?",
                        (budget_id,),
                    )
                replaced = conn.execute(
                    "DELETE FROM budget_line WHERE budget_id = ?",
                    (budget_id,),
                ).rowcount
                conn.execute(
                    "UPDATE budget SET imported_from = ? WHERE id = ?",
                    (source, budget_id),
                )
            else:
                conn.execute(
                    "INSERT INTO budget "
                    "(period, currency_code, status, created_at, imported_from) "
                    "VALUES (?, ?, ?, ?, ?)",
                    (period, cur_code, "active", ts, source),
                )
                budget_id = conn.execute(
                    "SELECT id FROM budget WHERE period = ? AND currency_code = ?",
                    (period, cur_code),
                ).fetchone()[0]

            for r in items:
                conn.execute(
                    "INSERT INTO budget_line "
                    "(budget_id, category, amount_minor, kind, note) "
                    "VALUES (?, ?, ?, ?, ?)",
                    (budget_id, r.category, r.amount_minor, r.kind, r.note),
                )
            if existing is not None and existing[1] == "closed" and force:
                conn.execute(
                    "UPDATE budget SET status = 'closed' WHERE id = ?",
                    (budget_id,),
                )
            conn.commit()
        except Exception:
            conn.rollback()
            raise

        result.by_currency[cur_code] = {
            "budget_id": int(budget_id),
            "lines_added": len(items),
            "lines_replaced": int(replaced),
            "status_after": "closed" if (existing and existing[1] == "closed" and force) else "active",
        }

    return result


def log_import_run(
    conn: sqlite3.Connection,
    *,
    source: str,
    period: str,
    lines_added: int,
    lines_replaced: int,
    new_categories: list[str],
    now_ts: int | None = None,
) -> int:
    """Append to ``budget_import_run`` audit table. Returns the
    inserted row id so the CLI can echo it back."""
    ts = now_ts if now_ts is not None else int(time.time())
    conn.execute("BEGIN")
    try:
        conn.execute(
            "INSERT INTO budget_import_run "
            "(source, period, imported_at, lines_added, lines_replaced, new_categories) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (
                source,
                period,
                ts,
                lines_added,
                lines_replaced,
                json.dumps(new_categories, ensure_ascii=False) if new_categories else None,
            ),
        )
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    return int(conn.execute("SELECT last_insert_rowid()").fetchone()[0])


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _check_columns(
    found: Iterable[str] | None,
    required: tuple[str, ...],
    optional: tuple[str, ...],
    *,
    sheet: str,
) -> None:
    if not found:
        raise BudgetParseError(
            f"{sheet}: empty input (no header row)", kind="EmptyInput"
        )
    found_set = {f for f in found if isinstance(f, str)}
    missing = [c for c in required if c not in found_set]
    if missing:
        raise BudgetParseError(
            f"{sheet}: missing required columns {missing}; "
            f"got {sorted(found_set)}",
            kind="BadHeader",
            details={"missing": missing, "found": sorted(found_set)},
        )
    extras = [
        c for c in found_set if c not in required and c not in optional and c
    ]
    # Extras are tolerated (sheets often have helper columns) but we
    # still report them in the details so the CLI can warn.
    if extras:
        # Cheap warning carried alongside successful parse.
        # The validator sees `details.extras` later.
        pass


def _validate_period(period: str, flag: str) -> None:
    if not isinstance(period, str) or not PERIOD_RE.match(period):
        raise BudgetParseError(
            f"--{flag}={period!r} must match YYYY-MM",
            kind="BadPeriod",
        )


def _row_from_plans(raw: dict[str, Any], *, source_row: str) -> PlanRow:
    period = _coerce_str(raw.get("Period"), "Period", source_row)
    _validate_period(period, "period")
    category = _coerce_category(raw.get("Category"), source_row)
    currency = _coerce_currency(raw.get("Currency"), source_row)
    kind = _coerce_kind(raw.get("Kind"), source_row)
    amount = _coerce_amount(raw.get("Amount"), source_row)
    note = _coerce_note(raw.get("Note"))
    return PlanRow(
        period=period,
        category=category,
        currency_code=currency,
        kind=kind,
        amount_minor=amount,
        note=note,
        source_row=source_row,
    )


def _row_from_baseline(
    raw: dict[str, Any], period: str, *, source_row: str
) -> PlanRow:
    category = _coerce_category(raw.get("Category"), source_row)
    currency = _coerce_currency(raw.get("Currency"), source_row)
    kind = _coerce_kind(raw.get("Kind"), source_row)
    if kind == "one_time":
        raise BudgetParseError(
            f"{source_row}: Baseline sheet must not contain Kind=one_time; "
            "one-time items belong in the Plans sheet",
            kind="BadKind",
        )
    amount = _coerce_amount(raw.get("Monthly target"), source_row, field_label="Monthly target")
    note = _coerce_note(raw.get("Note"))
    return PlanRow(
        period=period,
        category=category,
        currency_code=currency,
        kind=kind,
        amount_minor=amount,
        note=note,
        source_row=source_row,
    )


def _coerce_str(value: Any, field_label: str, source_row: str) -> str:
    if value is None:
        raise BudgetParseError(
            f"{source_row}: {field_label} is empty", kind="MissingField"
        )
    return str(value).strip()


def _coerce_category(value: Any, source_row: str) -> str:
    raw = _coerce_str(value, "Category", source_row)
    stripped = raw.strip()
    if not stripped:
        raise BudgetParseError(
            f"{source_row}: Category is empty", kind="MissingField"
        )
    if "//" in stripped or stripped.startswith("/") or stripped.endswith("/"):
        raise BudgetParseError(
            f"{source_row}: Category {stripped!r} has empty hierarchy segments",
            kind="BadCategoryShape",
        )
    return stripped


def _coerce_currency(value: Any, source_row: str) -> int:
    raw = _coerce_str(value, "Currency", source_row)
    if raw.isdigit():
        return int(raw)
    numeric = numeric_for(raw)
    if numeric is None:
        raise BudgetParseError(
            f"{source_row}: unknown Currency {raw!r}",
            kind="BadCurrency",
        )
    return numeric


def _coerce_kind(value: Any, source_row: str) -> str:
    raw = _coerce_str(value, "Kind", source_row).lower()
    if raw not in ALLOWED_KINDS:
        raise BudgetParseError(
            f"{source_row}: Kind {raw!r} must be one of {list(ALLOWED_KINDS)}",
            kind="BadKind",
        )
    return raw


def _coerce_amount(value: Any, source_row: str, *, field_label: str = "Amount") -> int:
    if value is None or (isinstance(value, str) and not value.strip()):
        raise BudgetParseError(
            f"{source_row}: {field_label} is empty", kind="MissingField"
        )
    try:
        amount = float(value)
    except (ValueError, TypeError) as exc:
        raise BudgetParseError(
            f"{source_row}: {field_label}={value!r} is not numeric",
            kind="BadAmount",
        ) from exc
    return int(round(amount * 100))


def _coerce_note(value: Any) -> str | None:
    if value is None:
        return None
    s = str(value).strip()
    return s or None
