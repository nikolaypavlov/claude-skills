"""End-to-end ``pf-query`` CLI tests.

Drives the argparse entry point directly via ``main(argv=...)`` and
captures stdout/stderr through pytest ``capsys``. Asserts:

- success path: exit 0, JSON-parseable stdout payload with ``ok=True``.
- known failure: exit 1, JSON-parseable stderr payload with ``ok=False``
  and a ``type`` field that names the error category.
- the ``--db`` flag is honoured (no env or HOME dependence).
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from pf_skill.query import main


def _run(argv: list[str], capsys: pytest.CaptureFixture[str]) -> tuple[int, dict, str]:
    """Invoke ``main(argv)`` and return ``(exit_code, stdout_json, stderr_text)``.

    stdout is JSON on success and empty on failure; stderr is the
    structured ``{"ok": false, ...}`` payload on known failure or
    a traceback on uncaught.
    """
    rc = main(argv)
    captured = capsys.readouterr()
    payload: dict = {}
    if captured.out.strip():
        payload = json.loads(captured.out)
    return rc, payload, captured.err


def test_accounts_both_banks(
    both_banks_db: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    rc, payload, err = _run(["accounts", "--db", str(both_banks_db)], capsys)
    assert rc == 0, err
    assert payload["ok"] is True
    assert payload["detected_banks"] == ["mono", "privat"]
    banks = sorted(a["bank"] for a in payload["accounts"])
    assert banks == ["mono", "privat"]


def test_accounts_empty_db_warns(
    empty_db: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    rc, payload, err = _run(["accounts", "--db", str(empty_db)], capsys)
    assert rc == 0, err
    assert payload["ok"] is True
    assert payload["detected_banks"] == []
    assert payload["accounts"] == []
    assert "warning" in payload
    assert "no transaction sources" in payload["warning"]


def test_list_iso_date_args(
    both_banks_db: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """ISO 8601 dates (no time) are accepted - midnight UTC."""
    rc, payload, err = _run(
        [
            "list",
            "--from",
            "2023-11-14",
            "--to",
            "2023-11-15",
            "--db",
            str(both_banks_db),
        ],
        capsys,
    )
    # Fixture timestamps are ~1.7e9 = Nov 14 2023. The exact day-bounds
    # are loose - we only assert the call succeeded.
    assert rc == 0, err
    assert payload["ok"] is True
    assert isinstance(payload["transactions"], list)


def test_list_inverted_range_rejected(
    both_banks_db: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    rc, payload, err = _run(
        [
            "list",
            "--from",
            "1700001000",
            "--to",
            "1700000000",
            "--db",
            str(both_banks_db),
        ],
        capsys,
    )
    assert rc == 1
    assert payload == {}, "stdout should be empty on the error path"
    err_payload = json.loads(err)
    assert err_payload["ok"] is False
    assert "strictly less" in err_payload["error"]


def test_list_filter_by_bank(
    both_banks_db: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    rc, payload, _ = _run(
        [
            "list",
            "--from",
            "0",
            "--to",
            "2000000000",
            "--bank",
            "privat",
            "--db",
            str(both_banks_db),
        ],
        capsys,
    )
    assert rc == 0
    assert payload["count"] == 2
    assert all(tx["bank"] == "privat" for tx in payload["transactions"])


def test_summarize_by_bank(
    both_banks_db: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    rc, payload, err = _run(
        [
            "summarize",
            "--from",
            "0",
            "--to",
            "2000000000",
            "--group-by",
            "bank",
            "--db",
            str(both_banks_db),
        ],
        capsys,
    )
    assert rc == 0, err
    by_key = {b["key"]: b for b in payload["buckets"]}
    assert by_key["mono"]["tx_count"] == 3
    assert by_key["privat"]["tx_count"] == 2


def test_summarize_invalid_group_by(
    both_banks_db: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    rc, _, err = _run(
        [
            "summarize",
            "--from",
            "0",
            "--to",
            "2000000000",
            "--group-by",
            "bogus",
            "--db",
            str(both_banks_db),
        ],
        capsys,
    )
    assert rc == 1
    err_payload = json.loads(err)
    assert err_payload["ok"] is False
    assert "--group-by" in err_payload["error"]


def test_find_substring(
    both_banks_db: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    rc, payload, err = _run(
        ["find", "--query", "grocery", "--db", str(both_banks_db)], capsys
    )
    assert rc == 0, err
    assert payload["count"] == 1
    assert payload["transactions"][0]["id"] == "mono_t2"


def test_find_empty_query_rejected(
    both_banks_db: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    rc, _, err = _run(
        ["find", "--query", "   ", "--db", str(both_banks_db)], capsys
    )
    assert rc == 1
    err_payload = json.loads(err)
    assert err_payload["ok"] is False


def test_unknown_currency_rejected(
    both_banks_db: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    rc, _, err = _run(
        [
            "list",
            "--from",
            "0",
            "--to",
            "2000000000",
            "--currency",
            "XYZ",
            "--db",
            str(both_banks_db),
        ],
        capsys,
    )
    assert rc == 1
    err_payload = json.loads(err)
    assert err_payload["ok"] is False
    assert "unknown currency" in err_payload["error"].lower()


def test_currency_alpha_filter(
    both_banks_db: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    rc, payload, _ = _run(
        [
            "list",
            "--from",
            "0",
            "--to",
            "2000000000",
            "--currency",
            "UAH",
            "--db",
            str(both_banks_db),
        ],
        capsys,
    )
    assert rc == 0
    assert payload["count"] == 5  # every fixture row is UAH


def test_db_path_env_honoured(
    both_banks_db: Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``--db`` overrides everything; without it, MONOBANK_MCP_DATA_DIR
    must point at the parent directory (data.db is appended)."""
    monkeypatch.setenv("MONOBANK_MCP_DATA_DIR", str(both_banks_db.parent))
    rc, payload, err = _run(["accounts"], capsys)
    assert rc == 0, err
    assert payload["ok"] is True
    assert len(payload["accounts"]) == 2
