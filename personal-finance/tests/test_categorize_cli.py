"""End-to-end ``pf-categorize`` CLI tests.

Same drive-via-main()+capsys pattern as test_query_cli.py. Asserts the
unified JSON contract: stdout JSON + exit 0 on success;
``{"ok": false, ...}`` on stderr + exit 1 on known failure.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from pf_skill.categorize import main


def _run(argv: list[str], capsys: pytest.CaptureFixture[str]) -> tuple[int, dict, str]:
    rc = main(argv)
    captured = capsys.readouterr()
    payload: dict = {}
    if captured.out.strip():
        payload = json.loads(captured.out)
    return rc, payload, captured.err


def test_scope_all_happy_path(both_banks_db: Path, capsys: pytest.CaptureFixture[str]) -> None:
    rc, payload, err = _run(["--scope", "all", "--db", str(both_banks_db)], capsys)
    assert rc == 0, err
    assert payload["ok"] is True
    assert payload["categorized_count"] >= 1
    assert "no_match_count" in payload
    assert payload["scope"]["scope"] == "all"


def test_scope_last_n_days_requires_n(
    both_banks_db: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    rc, _, err = _run(["--scope", "last-n-days", "--db", str(both_banks_db)], capsys)
    assert rc == 1
    err_payload = json.loads(err)
    assert err_payload["ok"] is False
    assert "--n" in err_payload["error"]


def test_scope_last_n_days_with_n(both_banks_db: Path, capsys: pytest.CaptureFixture[str]) -> None:
    rc, payload, err = _run(
        [
            "--scope",
            "last-n-days",
            "--n",
            "365000",  # very wide window so fixture tx are in range
            "--db",
            str(both_banks_db),
        ],
        capsys,
    )
    assert rc == 0, err
    assert payload["scope"]["scope"] == "last-n-days"
    assert payload["scope"]["from_ts"] is not None


def test_unknown_scope_rejected(both_banks_db: Path, capsys: pytest.CaptureFixture[str]) -> None:
    rc, _, err = _run(["--scope", "bogus", "--db", str(both_banks_db)], capsys)
    assert rc == 1
    err_payload = json.loads(err)
    assert err_payload["ok"] is False
    assert "--scope" in err_payload["error"]


def test_n_without_last_n_days_rejected(
    both_banks_db: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    rc, _, err = _run(["--scope", "all", "--n", "30", "--db", str(both_banks_db)], capsys)
    assert rc == 1
    err_payload = json.loads(err)
    assert err_payload["ok"] is False
    assert "--n" in err_payload["error"]


def test_empty_db_returns_zero(empty_db: Path, capsys: pytest.CaptureFixture[str]) -> None:
    rc, payload, err = _run(["--scope", "all", "--db", str(empty_db)], capsys)
    assert rc == 0, err
    assert payload["ok"] is True
    assert payload["categorized_count"] == 0
    assert payload["no_match_count"] == 0
