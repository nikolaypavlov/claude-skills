"""Shared pytest fixtures for the privat24-import test suite."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

# fixtures/ is a sibling of src/ - not a package, so make it importable
# directly without polluting the source tree.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from fixtures.generate import generate as generate_sample  # noqa: E402

REPO_FIXTURE = Path(__file__).resolve().parent.parent / "fixtures" / "sample_web.xlsx"


@pytest.fixture
def sample_xlsx(tmp_path: Path) -> Path:
    """Copy the canonical synthetic XLSX into a tmp dir.

    Most tests pass the path to a parser without writing to it; using a
    temp copy still keeps the suite hermetic if a future test were to
    mutate the file in place.
    """
    dest = tmp_path / "sample_web.xlsx"
    dest.write_bytes(REPO_FIXTURE.read_bytes())
    return dest


@pytest.fixture
def make_xlsx(tmp_path: Path):
    """Return a builder that regenerates a fresh XLSX with overridable seed.

    Use this when a test needs a deterministic but distinct file - e.g.
    "two different files containing the same logical transaction".
    """

    def _build(*, seed: int = 42, rows: int = 30, name: str = "gen.xlsx") -> Path:
        out = tmp_path / name
        return generate_sample(out, seed=seed, rows=rows)

    return _build
