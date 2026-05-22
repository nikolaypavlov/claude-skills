"""Bundled seed rules for the categorizer, loaded at runtime via
``importlib.resources``.

Layout matches ``pf_skill.schema``: every file in this package travels
with the installed wheel through ``[tool.setuptools.package-data]`` in
``pyproject.toml``. The categorizer reads them through
``resources.files("pf_skill.rules").joinpath(...).read_text()`` so the
path works in both source-tree and installed-wheel layouts.
"""
