"""``pf-query balances`` and the ``account_balances`` helper.

Covers the two balance sources - the authoritative per-account balance
that monobank-mcp >= 0.3 stores on ``mono_accounts`` (with credit line),
and the latest-transaction fallback for banks whose account table has no
balance column (privat, or a pre-0.3 mono row).
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest

from pf_skill.common import queries as q
from pf_skill.common.store import open_db
from pf_skill.query import main


def _run(argv: list[str], capsys: pytest.CaptureFixture[str]) -> tuple[int, dict, dict]:
    rc = main(argv)
    captured = capsys.readouterr()
    out: dict = json.loads(captured.out) if captured.out.strip() else {}
    err: dict = {}
    if captured.err.strip():
        try:
            err = json.loads(captured.err.splitlines()[-1])
        except json.JSONDecodeError:
            err = {"raw": captured.err}
    return rc, out, err


def _mono_with_balance_db(tmp_path: Path) -> Path:
    """A v0.3-shaped mono store: mono_accounts carries balance_minor /
    credit_limit_minor / balance_synced_at. One black-UAH card with a
    200k credit line, one black-USD card with no credit line, and one
    dormant account with no balance and no transactions."""
    db = tmp_path / "data.db"
    conn = sqlite3.connect(db)
    conn.executescript(
        """
        CREATE TABLE mono_accounts (
            account_id    TEXT PRIMARY KEY,
            iban          TEXT,
            type          TEXT,
            currency_code INTEGER NOT NULL,
            masked_pan    TEXT,
            label         TEXT,
            opened_at     INTEGER,
            balance_minor      INTEGER,
            credit_limit_minor INTEGER,
            balance_synced_at  INTEGER
        );
        CREATE TABLE mono_transactions (
            id            TEXT PRIMARY KEY,
            account_id    TEXT NOT NULL,
            ts            INTEGER NOT NULL,
            amount_minor  INTEGER NOT NULL,
            currency_code INTEGER NOT NULL,
            op_amount_minor  INTEGER,
            op_currency_code INTEGER,
            mcc           INTEGER,
            description   TEXT,
            counterparty  TEXT,
            balance_minor INTEGER,
            cashback_minor INTEGER,
            raw_json      TEXT NOT NULL,
            imported_at   INTEGER NOT NULL,
            import_run_id INTEGER NOT NULL
        );
        INSERT INTO mono_accounts VALUES
          ('black_uah', 'UA1', 'black', 980, '4444****', NULL, NULL,
           20199575, 20000000, 1700000000),
          ('black_usd', 'UA2', 'black', 840, '4444****', NULL, NULL,
           206282, NULL, 1700000000),
          ('dormant',   'UA3', 'diia',  980, NULL, NULL, NULL,
           NULL, NULL, NULL);
        """
    )
    conn.commit()
    conn.close()
    return db


def test_account_balance_prefers_stored_balance_and_subtracts_credit(
    tmp_path: Path,
) -> None:
    conn = open_db(_mono_with_balance_db(tmp_path))
    rows = {r["account_id"]: r for r in q.account_balances(conn)}
    conn.close()

    uah = rows["black_uah"]
    assert uah["balance_source"] == "account"
    assert uah["balance_minor"] == 20199575
    assert uah["credit_limit_minor"] == 20000000
    # real funds = balance - credit line
    assert uah["real_funds_minor"] == 199575
    assert uah["name"] == "Black-UAH"
    assert uah["balance_synced_at"] == 1700000000

    # No credit line: real funds == balance.
    usd = rows["black_usd"]
    assert usd["credit_limit_minor"] is None
    assert usd["real_funds_minor"] == 206282
    assert usd["name"] == "Black-USD"


def test_dormant_account_reports_unknown_balance(tmp_path: Path) -> None:
    conn = open_db(_mono_with_balance_db(tmp_path))
    rows = {r["account_id"]: r for r in q.account_balances(conn)}
    conn.close()
    dormant = rows["dormant"]
    assert dormant["balance_minor"] is None
    assert dormant["real_funds_minor"] is None
    assert dormant["balance_source"] == "none"
    # Single-currency type keeps a bare name.
    assert dormant["name"] == "Diia"


def test_account_balance_falls_back_to_latest_tx(mono_only_db: Path) -> None:
    """The conftest mono_accounts is v1-shaped (no balance columns), so
    the balance must come from the newest transaction's running balance."""
    conn = open_db(mono_only_db)
    rows = {r["account_id"]: r for r in q.account_balances(conn)}
    conn.close()
    acc = rows["mono_acc_1"]
    assert acc["balance_source"] == "transaction"
    # mono_t3 is the newest tx (ts 1_700_002_000) with balance 1_350_000.
    assert acc["balance_minor"] == 1_350_000
    assert acc["credit_limit_minor"] is None
    assert acc["real_funds_minor"] == 1_350_000
    # A stored label wins over the derived name.
    assert acc["name"] == "Mono UAH"


def test_cli_balances_groups_by_currency_with_totals(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    db = _mono_with_balance_db(tmp_path)
    rc, out, err = _run(["balances", "--db", str(db)], capsys)
    assert rc == 0, err
    by_cur = out["by_currency"]
    # UAH: black_uah real funds 199575 + dormant (unknown, excluded).
    assert by_cur["UAH"]["real_funds_minor_total"] == 199575
    assert by_cur["UAH"]["unknown_accounts"] == 1
    # USD: single account, no credit line.
    assert by_cur["USD"]["real_funds_minor_total"] == 206282
    assert by_cur["USD"]["unknown_accounts"] == 0


def test_cli_balances_converts_on_request(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    db = _mono_with_balance_db(tmp_path)
    rc, out, err = _run(
        ["balances", "--convert-to", "UAH", "--rate", "USD=44.5", "--db", str(db)],
        capsys,
    )
    assert rc == 0, err
    conv = out["converted"]
    assert conv["target_currency"] == "UAH"
    # UAH real funds 199575 at 1.0 + USD 206282 at 44.5 (=9179549).
    assert conv["total_minor"] == 199575 + round(206282 * 44.5)
    assert conv["unconverted"] == []


def test_cli_balances_flags_unconverted_currency(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """A held currency with no --rate must be flagged, not silently
    dropped from the converted total."""
    db = _mono_with_balance_db(tmp_path)
    rc, out, err = _run(["balances", "--convert-to", "UAH", "--db", str(db)], capsys)
    assert rc == 0, err
    assert out["converted"]["unconverted"] == ["USD"]
    # Only the UAH block (rate 1.0) is in the total.
    assert out["converted"]["total_minor"] == 199575


def test_cli_balances_rejects_malformed_rate(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    db = _mono_with_balance_db(tmp_path)
    rc, out, err = _run(
        ["balances", "--convert-to", "UAH", "--rate", "USD44.5", "--db", str(db)],
        capsys,
    )
    assert rc == 1
    assert "--rate" in json.dumps(err, ensure_ascii=False)


def test_display_name_helper() -> None:
    # multi-currency types get a suffix
    assert q.account_display_name(type_="black", currency_alpha="UAH", label=None) == "Black-UAH"
    assert q.account_display_name(type_="fop", currency_alpha="USD", label=None) == "FOP-USD"
    # single-currency types stay bare
    assert q.account_display_name(type_="eAid", currency_alpha="UAH", label=None) == "eAid"
    # label always wins
    assert q.account_display_name(type_="black", currency_alpha="UAH", label="My card") == "My card"
    # unknown single-currency type falls back to a title-cased bare form
    assert q.account_display_name(type_="revolut", currency_alpha="EUR", label=None) == "Revolut"


def _stale_snapshot_db(tmp_path: Path) -> Path:
    """Same v0.3 shape, but the black-UAH snapshot predates the newest
    transaction on that account - exactly what `monobank-mcp sync` leaves
    behind, since sync writes transactions and never refreshes balances.
    black-USD stays current so the flag is proven to be per-account.
    """
    db = _mono_with_balance_db(tmp_path)
    conn = sqlite3.connect(db)
    conn.executescript(
        """
        INSERT INTO mono_transactions VALUES
          ('t_uah_new', 'black_uah', 1700009999, -50000, 980,
           NULL, NULL, 5411, 'Silpo', NULL, 20149575, NULL, '{}', 1, 1),
          ('t_usd_old', 'black_usd', 1699990000, -1000, 840,
           NULL, NULL, 5411, 'Amazon', NULL, 206282, NULL, '{}', 1, 1);
        """
    )
    conn.commit()
    conn.close()
    return db


def test_balance_flagged_stale_when_snapshot_predates_newest_tx(
    tmp_path: Path,
) -> None:
    conn = open_db(_stale_snapshot_db(tmp_path))
    rows = {r["account_id"]: r for r in q.account_balances(conn)}
    conn.close()

    uah = rows["black_uah"]
    assert uah["balance_stale"] is True
    assert uah["newest_tx_ts"] == 1700009999
    assert uah["balance_synced_at"] == 1700000000

    # Snapshot newer than its newest transaction: not stale.
    usd = rows["black_usd"]
    assert usd["balance_stale"] is False
    assert usd["newest_tx_ts"] == 1699990000


def test_balance_not_stale_without_transactions(tmp_path: Path) -> None:
    """A dormant account has no transactions to be behind of."""
    conn = open_db(_mono_with_balance_db(tmp_path))
    rows = {r["account_id"]: r for r in q.account_balances(conn)}
    conn.close()
    assert rows["black_uah"]["balance_stale"] is False
    assert rows["dormant"]["balance_stale"] is False
    assert rows["dormant"]["newest_tx_ts"] is None


def test_transaction_sourced_balance_is_never_stale(mono_only_db: Path) -> None:
    """The fallback reads the newest transaction itself, so it cannot lag
    behind one."""
    conn = open_db(mono_only_db)
    rows = {r["account_id"]: r for r in q.account_balances(conn)}
    conn.close()
    acc = rows["mono_acc_1"]
    assert acc["balance_source"] == "transaction"
    assert acc["balance_stale"] is False


def test_cli_balances_surfaces_stale_snapshot_at_top_level(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    db = _stale_snapshot_db(tmp_path)
    rc, out, _ = _run(["balances", "--db", str(db)], capsys)
    assert rc == 0
    stale = out["stale_balances"]
    assert stale["count"] == 1
    assert [a["account_id"] for a in stale["accounts"]] == ["black_uah"]
    assert "monobank-mcp accounts" in stale["warning"]


def test_cli_balances_omits_stale_block_when_all_current(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    db = _mono_with_balance_db(tmp_path)
    rc, out, _ = _run(["balances", "--db", str(db)], capsys)
    assert rc == 0
    assert "stale_balances" not in out
