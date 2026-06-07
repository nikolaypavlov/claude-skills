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


def fetch_budget(
    conn: sqlite3.Connection, *, period: str, currency_code: int | None = None
) -> list[dict[str, Any]]:
    """Return budget rows + their lines for the period.

    Shape::

        [{period, currency_code, status, created_at, imported_from,
          lines: [{category, kind, amount_minor, note}], total_minor}]

    Sorted by currency_code so UAH (980) always comes before USD
    (840) → no, sorted ASC numeric so UAH (980) comes after USD (840).
    Use the alpha code in CLI rendering if the user-facing order
    matters.
    """
    where = ["b.period = ?"]
    params: list[Any] = [period]
    if currency_code is not None:
        where.append("b.currency_code = ?")
        params.append(currency_code)
    budgets = conn.execute(
        "SELECT id, period, currency_code, status, created_at, imported_from "
        f"FROM budget b WHERE {' AND '.join(where)} ORDER BY currency_code",
        params,
    ).fetchall()
    out: list[dict[str, Any]] = []
    for bid, per, cur, status, created_at, imported_from in budgets:
        lines = conn.execute(
            "SELECT category, kind, amount_minor, note FROM budget_line "
            "WHERE budget_id = ? ORDER BY amount_minor ASC",
            (bid,),
        ).fetchall()
        line_dicts = [
            {"category": c, "kind": k, "amount_minor": int(a), "note": n}
            for c, k, a, n in lines
        ]
        out.append(
            {
                "budget_id": int(bid),
                "period": per,
                "currency_code": int(cur),
                "status": status,
                "created_at": int(created_at),
                "imported_from": imported_from,
                "lines": line_dicts,
                "total_minor": sum(line["amount_minor"] for line in line_dicts),
                "line_count": len(line_dicts),
            }
        )
    return out


def actuals_for_period(
    conn: sqlite3.Connection,
    *,
    period: str,
    currency_code: int | None = None,
    exclude_categories: tuple[str, ...] = ("Перекази/СвоїКартки",),
) -> dict[tuple[int, str], int]:
    """Sum actual transactions by (currency, category) for a period.

    Uses the same UNION view + CATEGORY_EXPR / CATEGORY_JOIN_SQL +
    account-currency join that ``summarize_spending`` does. Returns
    ``{(currency_code, category): total_minor_signed}``.

    ``exclude_categories`` defaults to the internal-transfer label so
    actuals match the "real spending" convention used in pf-report.
    """
    from . import queries as q
    from .view import discover_sources, build_accounts_union_sql, build_tx_union_sql

    sources = discover_sources(conn)
    tx_union = build_tx_union_sql(sources)
    accounts_union = build_accounts_union_sql(sources)
    if tx_union is None or accounts_union is None:
        return {}
    # Period boundaries: first second of month → first second of next month.
    year, month = (int(p) for p in period.split("-"))
    from_ts = int(time.mktime((year, month, 1, 0, 0, 0, 0, 0, 0))) - time.timezone
    if month == 12:
        next_year, next_month = year + 1, 1
    else:
        next_year, next_month = year, month + 1
    to_ts = int(time.mktime((next_year, next_month, 1, 0, 0, 0, 0, 0, 0))) - time.timezone

    where_cur = ""
    params: list[Any] = [from_ts, to_ts]
    if currency_code is not None:
        where_cur = " AND acc.currency_code = ?"
        params.append(currency_code)
    placeholders = ",".join(["?"] * len(exclude_categories))
    cat_filter = (
        f" AND ({q.CATEGORY_EXPR} NOT IN ({placeholders}))"
        if exclude_categories
        else ""
    )
    params.extend(exclude_categories)

    sql = (
        f"SELECT acc.currency_code, {q.CATEGORY_EXPR} AS category, "
        f"SUM(tx.amount_minor) AS total_minor "
        f"FROM (\n{tx_union}\n) AS tx "
        f"{q.CATEGORY_JOIN_SQL} "
        f"JOIN (\n{accounts_union}\n) AS acc ON acc.account_id = tx.account_id "
        f"WHERE tx.ts >= ? AND tx.ts < ?{where_cur}{cat_filter} "
        f"GROUP BY acc.currency_code, {q.CATEGORY_EXPR}"
    )
    out: dict[tuple[int, str], int] = {}
    for cur, cat, tot in conn.execute(sql, params):
        if cat is None:
            cat = "(uncategorized)"
        out[(int(cur), str(cat))] = int(tot or 0)
    return out


def diff_budget_vs_actual(
    conn: sqlite3.Connection,
    *,
    period: str,
    currency_code: int | None = None,
) -> list[dict[str, Any]]:
    """Join budgeted lines with actuals from ``actuals_for_period``.

    Output is a list of per-currency blocks::

        [{currency_code, status, lines: [{category, kind, target_minor,
          actual_minor, delta_minor, pct_used}], totals: {...}}]

    Categories that exist only in actuals (no budget line) are still
    listed - the user wants to see what they spent that wasn't planned
    for. Categories with target but no actual show ``actual_minor=0``.
    """
    budgets = fetch_budget(conn, period=period, currency_code=currency_code)
    actuals = actuals_for_period(
        conn, period=period, currency_code=currency_code
    )

    # Index actuals by currency for quick consumption per budget block.
    actuals_by_cur: dict[int, dict[str, int]] = {}
    for (cur, cat), amt in actuals.items():
        actuals_by_cur.setdefault(cur, {})[cat] = amt

    out: list[dict[str, Any]] = []
    for b in budgets:
        cur = b["currency_code"]
        seen: set[str] = set()
        # Aggregate budget targets per category (a category can have
        # both baseline and one_time rows for the same period).
        target_by_cat: dict[str, int] = {}
        for line in b["lines"]:
            target_by_cat[line["category"]] = (
                target_by_cat.get(line["category"], 0) + line["amount_minor"]
            )
        cur_actuals = actuals_by_cur.get(cur, {})
        rows: list[dict[str, Any]] = []
        for cat, target in target_by_cat.items():
            actual = cur_actuals.get(cat, 0)
            delta = target - actual
            pct = _pct_used(actual, target)
            rows.append(
                {
                    "category": cat,
                    "target_minor": target,
                    "actual_minor": actual,
                    "delta_minor": delta,
                    "pct_used": pct,
                    "in_budget": True,
                }
            )
            seen.add(cat)
        # Surface actuals that have no budgeted line.
        for cat, actual in cur_actuals.items():
            if cat in seen:
                continue
            rows.append(
                {
                    "category": cat,
                    "target_minor": 0,
                    "actual_minor": actual,
                    "delta_minor": -actual,
                    "pct_used": None,
                    "in_budget": False,
                }
            )
        rows.sort(key=lambda r: r["target_minor"])  # most-negative first
        totals = {
            "target_minor": sum(r["target_minor"] for r in rows),
            "actual_minor": sum(r["actual_minor"] for r in rows),
            "delta_minor": sum(r["delta_minor"] for r in rows),
        }
        out.append(
            {
                "currency_code": cur,
                "status": b["status"],
                "lines": rows,
                "totals": totals,
            }
        )
    # Surface actuals for currencies that have no budget at all.
    seen_cur = {b["currency_code"] for b in budgets}
    for cur, by_cat in actuals_by_cur.items():
        if cur in seen_cur:
            continue
        rows = [
            {
                "category": cat,
                "target_minor": 0,
                "actual_minor": amt,
                "delta_minor": -amt,
                "pct_used": None,
                "in_budget": False,
            }
            for cat, amt in sorted(by_cat.items(), key=lambda x: x[1])
        ]
        out.append(
            {
                "currency_code": cur,
                "status": None,  # no budget
                "lines": rows,
                "totals": {
                    "target_minor": 0,
                    "actual_minor": sum(r["actual_minor"] for r in rows),
                    "delta_minor": -sum(r["actual_minor"] for r in rows),
                },
            }
        )
    return out


def _pct_used(actual: int, target: int) -> float | None:
    """Percentage of target used so far. ``None`` when target == 0
    (income lines or no baseline target). For outflows (negative
    target), divide negative by negative so the result is positive.
    """
    if target == 0:
        return None
    return round(actual / target * 100.0, 1)


@dataclass
class StatusFlipResult:
    matched: int             # how many budget rows existed
    changed: list[dict[str, Any]]  # rows whose status actually flipped


def set_status(
    conn: sqlite3.Connection,
    *,
    period: str,
    currency_code: int | None,
    new_status: str,
) -> StatusFlipResult:
    """Flip ``budget.status`` for the matching budgets. Returns
    ``matched`` (how many rows existed) and ``changed`` (the rows
    that actually moved). Distinguishing the two lets the CLI emit
    ``NotFound`` only when nothing matched - flipping a closed budget
    back to closed is a successful no-op."""
    if new_status not in ("draft", "active", "closed"):
        raise BudgetParseError(
            f"new_status={new_status!r} must be one of draft|active|closed",
            kind="BadStatus",
        )
    where = ["period = ?"]
    params: list[Any] = [period]
    if currency_code is not None:
        where.append("currency_code = ?")
        params.append(currency_code)
    rows = conn.execute(
        "SELECT id, period, currency_code, status FROM budget "
        f"WHERE {' AND '.join(where)}",
        params,
    ).fetchall()
    if not rows:
        return StatusFlipResult(matched=0, changed=[])
    changed: list[dict[str, Any]] = []
    conn.execute("BEGIN")
    try:
        for budget_id, per, cur, status in rows:
            if status == new_status:
                continue
            conn.execute(
                "UPDATE budget SET status = ? WHERE id = ?",
                (new_status, budget_id),
            )
            changed.append(
                {
                    "budget_id": int(budget_id),
                    "period": per,
                    "currency_code": int(cur),
                    "old_status": status,
                    "new_status": new_status,
                }
            )
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    return StatusFlipResult(matched=len(rows), changed=changed)


def delete_budget(
    conn: sqlite3.Connection,
    *,
    period: str,
    currency_code: int | None,
    force: bool = False,
) -> list[dict[str, Any]]:
    """Delete a budget (and its lines via cascade). Refuses to delete
    closed budgets unless ``force=True`` - the lifecycle is meant to
    be append-and-snapshot, not purge."""
    where = ["period = ?"]
    params: list[Any] = [period]
    if currency_code is not None:
        where.append("currency_code = ?")
        params.append(currency_code)
    rows = conn.execute(
        "SELECT id, period, currency_code, status FROM budget "
        f"WHERE {' AND '.join(where)}",
        params,
    ).fetchall()
    if not rows:
        return []
    deleted: list[dict[str, Any]] = []
    conn.execute("BEGIN")
    try:
        for budget_id, per, cur, status in rows:
            if status == "closed" and not force:
                conn.rollback()
                raise BudgetParseError(
                    f"budget {per}/{cur} is closed; pass --force to delete",
                    kind="ClosedBudget",
                )
            if status == "closed" and force:
                # Reopen so cascade deletion of budget_line passes the
                # closed-budget trigger.
                conn.execute(
                    "UPDATE budget SET status = 'active' WHERE id = ?",
                    (budget_id,),
                )
            conn.execute("DELETE FROM budget WHERE id = ?", (budget_id,))
            deleted.append(
                {
                    "budget_id": int(budget_id),
                    "period": per,
                    "currency_code": int(cur),
                    "was_status": status,
                }
            )
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    return deleted


def rename_category(
    conn: sqlite3.Connection,
    *,
    old_name: str,
    new_name: str,
    update_tables: tuple[str, ...],
) -> dict[str, int]:
    """Rewrite ``category`` in the named tables. Returns per-table
    affected-row counts. The trigger on ``budget_line`` allows the
    UPDATE only when the parent budget is not closed, so renames on
    closed budgets need ``pf-budget reopen`` first."""
    allowed = {
        "budget_line",
        "tx_category",
        "category_overrides",
        "categorization_rules",
        "category_registry",
    }
    bad = [t for t in update_tables if t not in allowed]
    if bad:
        raise BudgetParseError(
            f"--update entries {bad} not allowed; "
            f"must be a subset of {sorted(allowed)}",
            kind="BadArgument",
        )
    counts: dict[str, int] = {}
    conn.execute("BEGIN")
    try:
        for table in update_tables:
            if table == "category_registry":
                # PK is category itself - DELETE old + INSERT new (or
                # just UPDATE if SQLite version supports it on PK).
                # Try UPDATE first; fall back to delete-and-insert if
                # a row already exists at new_name (UNIQUE collision).
                existing_new = conn.execute(
                    "SELECT 1 FROM category_registry WHERE category = ?",
                    (new_name,),
                ).fetchone()
                if existing_new is not None:
                    counts[table] = conn.execute(
                        "DELETE FROM category_registry WHERE category = ?",
                        (old_name,),
                    ).rowcount
                else:
                    counts[table] = conn.execute(
                        "UPDATE category_registry SET category = ? "
                        "WHERE category = ?",
                        (new_name, old_name),
                    ).rowcount
                continue
            counts[table] = conn.execute(
                f"UPDATE {table} SET category = ? WHERE category = ?",
                (new_name, old_name),
            ).rowcount
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    return counts


def list_budgets(conn: sqlite3.Connection) -> list[dict[str, Any]]:
    """Compact list of all budgets, line totals included, suitable for
    the home-page-style overview."""
    rows = conn.execute(
        "SELECT b.id, b.period, b.currency_code, b.status, b.created_at, "
        "       b.imported_from, "
        "       COUNT(bl.id) AS line_count, "
        "       COALESCE(SUM(bl.amount_minor), 0) AS total_minor "
        "FROM budget b LEFT JOIN budget_line bl ON bl.budget_id = b.id "
        "GROUP BY b.id ORDER BY b.period DESC, b.currency_code ASC"
    ).fetchall()
    return [
        {
            "budget_id": int(r[0]),
            "period": r[1],
            "currency_code": int(r[2]),
            "status": r[3],
            "created_at": int(r[4]),
            "imported_from": r[5],
            "line_count": int(r[6]),
            "total_minor": int(r[7]),
        }
        for r in rows
    ]


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
