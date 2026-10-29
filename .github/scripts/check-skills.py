#!/usr/bin/env python3
"""Validate agent-skill packaging in skills/.

The skills CLI (vercel-labs/skills) discovers a skill only when a directory
contains a SKILL.md whose YAML frontmatter declares, at minimum, ``name`` and
``description``. Plain markdown files with no frontmatter are silently ignored,
which is how this repository's skills went undiscoverable.

This check fails the build when a skill does not meet that contract, so the
packaging cannot regress. Stdlib only — no PyYAML, so CI needs no extra install.

Exit codes: 0 all skills valid (or none present), 1 violations found.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

SKILLS_DIR = Path(__file__).resolve().parents[2] / "skills"
NAME_RE = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
REQUIRED = ("name", "description")
DESC_MIN, DESC_MAX = 20, 1024
NAME_MAX = 64


def parse_frontmatter(text: str) -> tuple[dict[str, str], int]:
    """Return (flat key/value frontmatter, line index where the body starts).

    Handles only the flat ``key: value`` subset skills actually use. Values may
    be quoted and may wrap onto indented continuation lines.
    """
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        return {}, 0

    meta: dict[str, str] = {}
    key: str | None = None
    for idx, raw in enumerate(lines[1:], start=1):
        if raw.strip() == "---":
            return meta, idx + 1
        if not raw.strip():
            continue
        if raw[0] in " \t" and key:  # continuation of the previous value
            meta[key] = f"{meta[key]} {raw.strip()}".strip()
            continue
        k, sep, v = raw.partition(":")
        if not sep:
            continue
        key = k.strip()
        meta[key] = v.strip().strip("\"'")
    return {}, 0  # unterminated frontmatter


def check_skill(skill_dir: Path) -> list[str]:
    problems: list[str] = []
    skill_md = skill_dir / "SKILL.md"
    rel = skill_md.relative_to(SKILLS_DIR.parent)

    if not skill_md.is_file():
        return [f"{rel}: missing SKILL.md (skills must be skills/<name>/SKILL.md)"]

    text = skill_md.read_text(encoding="utf-8")
    meta, body_start = parse_frontmatter(text)

    if not meta:
        problems.append(f"{rel}: no YAML frontmatter (file must start with '---' and close it)")
        return problems

    for field in REQUIRED:
        if not meta.get(field):
            problems.append(f"{rel}: frontmatter is missing a non-empty '{field}'")

    name = meta.get("name", "")
    if name:
        if name != skill_dir.name:
            problems.append(f"{rel}: name '{name}' does not match directory '{skill_dir.name}'")
        if not NAME_RE.match(name):
            problems.append(f"{rel}: name '{name}' must be lowercase kebab-case")
        if len(name) > NAME_MAX:
            problems.append(f"{rel}: name '{name}' exceeds {NAME_MAX} characters")

    desc = meta.get("description", "")
    if desc and not (DESC_MIN <= len(desc) <= DESC_MAX):
        problems.append(
            f"{rel}: description is {len(desc)} chars; expected {DESC_MIN}-{DESC_MAX}"
        )

    body = "\n".join(text.splitlines()[body_start:]).strip()
    if not body:
        problems.append(f"{rel}: body is empty after frontmatter")

    return problems


def main() -> int:
    if not SKILLS_DIR.is_dir():
        print(f"SKIP: no {SKILLS_DIR.name}/ directory")
        return 0

    subdirs = sorted(p for p in SKILLS_DIR.iterdir() if p.is_dir())
    skill_dirs = [p for p in subdirs if (p / "SKILL.md").is_file()]
    # Directories holding only legacy .md files are pre-migration groupings, not
    # skills. They warn rather than fail so the migration can land incrementally.
    legacy_groups = [p for p in subdirs if p not in skill_dirs and any(p.rglob("*.md"))]
    stray_dirs = [p for p in subdirs if p not in skill_dirs and p not in legacy_groups]

    problems: list[str] = []
    for skill_dir in skill_dirs:
        found = check_skill(skill_dir)
        problems.extend(found)
        status = "FAIL" if found else "PASS"
        print(f"{status}: skills/{skill_dir.name}")

    for stray in stray_dirs:
        problems.append(f"skills/{stray.name}: directory has no SKILL.md and no markdown content")

    for path in sorted(p for p in SKILLS_DIR.rglob("*.md") if p.name != "SKILL.md"):
        print(f"WARN: {path.relative_to(SKILLS_DIR.parent)} has no frontmatter — not discoverable")

    print()
    if problems:
        print(f"FAILED: {len(problems)} skill packaging problem(s)")
        for problem in problems:
            print(f"  - {problem}")
        return 1

    print(
        f"PASSED: {len(skill_dirs)} skill(s) valid, "
        f"{len(legacy_groups)} legacy group(s) + flat files pending migration"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
