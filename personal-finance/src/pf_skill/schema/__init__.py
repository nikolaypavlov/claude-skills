"""pf_* migration SQL, loaded at runtime via ``importlib.resources``.

This package exists so the SQL travels with the installed wheel - the
file at ``src/pf_skill/schema/pf_001_initial.sql`` is picked up by
``[tool.setuptools.package-data]`` and accessed at runtime through
``resources.files("pf_skill.schema").joinpath(...).read_text()``.
"""
