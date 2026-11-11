#!/usr/bin/env python3
"""Validate agent-skill packaging in skills/.

The skills CLI (vercel-labs/skills) discovers a skill only when a directory
contains a SKILL.md whose YAML frontmatter declares, at minimum, ``name`` and
``description``. Plain markdown files with no frontmatter are silently ignored,
which is how this repository's skills went undiscoverable.

This check fails the build when a skill does not meet that contract, so the
packaging cannot regress. Stdlib only — no PyYAML, so CI needs no extra install.

Exit codes: 0 all skills valid (or none present), 1 violations found.

Rules enforced — see scripts/gen-docs.py for the `gate:` convention:

gate: skill-frontmatter-valid: every skills/<name>/SKILL.md declares name and description, kebab-case, matching its directory [required]
gate: cited-skills-exist: no document cites a skill path that resolves to no directory [required]
gate: skill-counts-current: no document states a SKILL.md count the tree contradicts [required]
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
SKILLS_DIR = REPO_ROOT / "skills"
AGENTS_SKILLS_DIR = REPO_ROOT / ".agents" / "skills"
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


# ── citation checks (--citations) ──────────────────────────────────────────
# Packaging validation above answers "is each skill a valid skill?". It cannot
# answer "does every skill this repo *mentions* exist?", and that is how
# ~/.agents/skills/research-investigation-pipeline/SKILL.md survived four
# citations across four documents while nothing installed it. Same for prose
# asserting a skill count the tree had doubled past.
#
# Scope is deliberately narrow, because a noisy check gets bypassed:
#   - only backticked `skills/<name>` references (a URL slug in prose is not a
#     citation, and matching bare words flagged lobehub/repo slugs as phantoms)
#   - template placeholders (<name>, globs) are skipped — they describe a shape
#   - a line may opt out with an inline `skills-ignore` marker, used for
#     historical references that must keep naming the thing that was wrong
CITATION_RE = re.compile(r"`((?:~/\.agents/|\.agents/)?skills/[^`\s]+)`")
COUNT_RE = re.compile(r"(\d+)\s+(?:conceptual\s+)?(?:skill\s+)?SKILL\.md\s+files", re.I)
PLACEHOLDER_RE = re.compile(r"[<>*]")
URL_LINE_RE = re.compile(r"https?://")
IGNORE_MARKER = "skills-ignore"

DOC_GLOBS = ("*.md", "docs/**/*.md", ".github/**/*.md")


def iter_docs() -> list[Path]:
    """Repo prose that can make claims about skills. Generated files included:
    a generator writing a phantom is still a phantom."""
    seen: dict[Path, None] = {}
    for pattern in DOC_GLOBS:
        for path in REPO_ROOT.glob(pattern):
            if any(part in {".git", ".venv", "node_modules", "__pycache__"}
                   for part in path.parts):
                continue
            seen[path] = None
    return sorted(seen)


def _documented_counts() -> dict[str, int]:
    """The counts a document may cite, keyed by what it is describing."""
    skills = {p.name for p in SKILLS_DIR.iterdir() if (p / "SKILL.md").is_file()} \
        if SKILLS_DIR.is_dir() else set()
    vendored = {p.name for p in AGENTS_SKILLS_DIR.iterdir() if p.is_dir()} \
        if AGENTS_SKILLS_DIR.is_dir() else set()
    return {"skills": len(skills), "all": len(skills | vendored)}


def check_citations() -> list[str]:
    """Phantom skill citations and stale 'N SKILL.md files' counts."""
    problems: list[str] = []
    known = {p.name for p in SKILLS_DIR.iterdir() if p.is_dir()} if SKILLS_DIR.is_dir() else set()
    if AGENTS_SKILLS_DIR.is_dir():
        known |= {p.name for p in AGENTS_SKILLS_DIR.iterdir() if p.is_dir()}
    counts = _documented_counts()
    expected = counts["skills"]

    for doc in iter_docs():
        rel = doc.relative_to(REPO_ROOT)
        for lineno, line in enumerate(doc.read_text(encoding="utf-8", errors="replace").splitlines(), 1):
            if IGNORE_MARKER in line or URL_LINE_RE.search(line):
                continue
            for match in CITATION_RE.finditer(line):
                cited = match.group(1)
                if PLACEHOLDER_RE.search(cited):
                    continue
                name = cited.split("skills/", 1)[1].split("/")[0]
                if name and name not in known:
                    problems.append(
                        f"{rel}:{lineno}: cites `{cited}` but no such skill exists "
                        f"in skills/ or .agents/skills/"
                    )
            for match in COUNT_RE.finditer(line):
                claimed = int(match.group(1))
                # A count may legitimately describe the vendored subset; only a
                # claim that matches neither total is a contradiction.
                if claimed not in (expected, counts["all"]):
                    problems.append(
                        f"{rel}:{lineno}: claims '{match.group(0)}' but skills/ has "
                        f"{expected} ({counts['all']} including .agents/skills/)"
                    )
    return problems


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Validate skills/ packaging.")
    parser.add_argument("--citations", action="store_true",
                        help="also flag citations of skills that do not exist, "
                             "and stale 'N SKILL.md files' counts")
    args = parser.parse_args(argv)

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

    citation_problems: list[str] = []
    if args.citations:
        citation_problems = check_citations()
        if not citation_problems:
            print(f"PASS: citations — every cited skill exists ({_scanned()} documents)")

    print()
    if problems or citation_problems:
        total = len(problems) + len(citation_problems)
        print(f"FAILED: {total} problem(s)")
        for problem in problems + citation_problems:
            print(f"  - {problem}")
        return 1

    print(
        f"PASSED: {len(skill_dirs)} skill(s) valid, "
        f"{len(legacy_groups)} legacy group(s) + flat files pending migration"
    )
    return 0


def _scanned() -> int:
    return len(iter_docs())


if __name__ == "__main__":
    sys.exit(main())
