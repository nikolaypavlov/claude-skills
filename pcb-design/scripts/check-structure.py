#!/usr/bin/env python3
"""Structural checks for the pcb-design plugin.

Documentation-only plugins have no test suite, so this is what stands in for
one. Run it from the repository root or from anywhere:

    python3 pcb-design/scripts/check-structure.py

Checks:
  1. every skill's frontmatter name matches its directory name
  2. every reference file is mentioned by its SKILL.md, and every reference a
     SKILL.md points at exists
  3. agents and commands carry the frontmatter fields the harness reads, and
     agents keep their read-only contract
  4. YAML templates parse, if pyyaml is importable
  5. no em dashes, curly quotes, ellipsis characters, unicode bullets or
     non-breaking spaces anywhere in the plugin

Exit code 1 on any failure, with one line per problem.
"""

from __future__ import annotations

import pathlib
import re
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent

# Built from code points on purpose: writing the characters themselves would
# make this file fail its own typography check.
FORBIDDEN = {
    chr(0x2014): "em dash",
    chr(0x2013): "en dash",
    chr(0x2018): "curly quote",
    chr(0x2019): "curly quote",
    chr(0x201C): "curly quote",
    chr(0x201D): "curly quote",
    chr(0x2026): "ellipsis character",
    chr(0x2022): "unicode bullet",
    chr(0x00A0): "non-breaking space",
}

problems: list[str] = []


def rel(path: pathlib.Path) -> str:
    return str(path.relative_to(ROOT.parent))


def frontmatter(path: pathlib.Path) -> dict[str, str]:
    """Flat key/value frontmatter read, enough for name/description/tools."""
    lines = path.read_text().splitlines()
    if not lines or lines[0].strip() != "---":
        problems.append(f"{rel(path)}: no opening frontmatter fence")
        return {}
    fields: dict[str, str] = {}
    key: str | None = None
    for line in lines[1:]:
        if line.strip() == "---":
            return fields
        if line.startswith((" ", "\t", "-")) and key:
            fields[key] += " " + line.strip()
            continue
        if ":" in line:
            key, _, value = line.partition(":")
            key = key.strip()
            fields[key] = value.strip()
    problems.append(f"{rel(path)}: no closing frontmatter fence")
    return fields


def check_skills() -> None:
    skills = sorted(ROOT.glob("skills/*/SKILL.md"))
    if not skills:
        problems.append("no skills found")
    for skill in skills:
        fields = frontmatter(skill)
        name = fields.get("name", "")
        if name != skill.parent.name:
            problems.append(
                f"{rel(skill)}: name {name!r} != directory {skill.parent.name!r}"
            )
        if len(fields.get("description", "")) < 80:
            problems.append(f"{rel(skill)}: description too short to route on")
        body = skill.read_text()
        for ref in sorted((skill.parent / "references").glob("*.md")):
            if ref.name not in body:
                problems.append(f"{rel(skill)}: never mentions {ref.name}")
        for ref_name in set(re.findall(r"references/([a-z0-9-]+\.md)", body)):
            if not (skill.parent / "references" / ref_name).is_file():
                problems.append(
                    f"{rel(skill)}: points at missing references/{ref_name}"
                )
        print(f"skill {name}: ok")


def check_agents() -> None:
    for agent in sorted(ROOT.glob("agents/*.md")):
        fields = frontmatter(agent)
        if fields.get("name", "") != agent.stem:
            problems.append(
                f"{rel(agent)}: name {fields.get('name')!r} != file {agent.stem!r}"
            )
        for required in ("description", "tools", "model"):
            if required not in fields:
                problems.append(f"{rel(agent)}: missing {required}")
        if "You review. You do not fix." not in agent.read_text():
            problems.append(f"{rel(agent)}: missing the read-only contract sentence")
        print(f"agent {fields.get('name')}: ok")


def check_commands() -> None:
    for cmd in sorted(ROOT.glob("commands/*.md")):
        if "description" not in frontmatter(cmd):
            problems.append(f"{rel(cmd)}: missing description")
        print(f"command {cmd.stem}: ok")


def check_yaml() -> None:
    try:
        import yaml
    except ImportError:
        print("pyyaml not importable: skipped YAML parse check")
        return
    for path in sorted(ROOT.glob("assets/**/*.yaml")):
        try:
            yaml.safe_load(path.read_text())
        except yaml.YAMLError as exc:
            problems.append(f"{rel(path)}: does not parse ({exc.__class__.__name__})")
        else:
            print(f"template {path.name}: parses")


def check_typography() -> None:
    for path in sorted(ROOT.rglob("*")):
        if not path.is_file() or path.suffix not in {".md", ".yaml", ".py"}:
            continue
        text = path.read_text()
        for char, label in FORBIDDEN.items():
            if char in text:
                line = text[: text.index(char)].count("\n") + 1
                problems.append(f"{rel(path)}:{line}: {label}")
    print("typography: checked")


def main() -> int:
    check_skills()
    check_agents()
    check_commands()
    check_yaml()
    check_typography()
    print()
    if problems:
        print("PROBLEMS:")
        for problem in problems:
            print(" -", problem)
        return 1
    print("all structural checks passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
