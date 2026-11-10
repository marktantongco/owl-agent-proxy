#!/usr/bin/env python3
"""Self-tests for the citation mode of .github/scripts/check-skills.py.

A checker that has never been made to fail is a green light with a test suite
attached. These tests build a throwaway repo tree and point the checker's
module-level paths at it, so each rule is exercised both ways: the defect it
exists to catch, and the near-misses it must not flag.

Run: python tests/test_skills_citations.py
"""
from __future__ import annotations

import importlib.util
import sys
import tempfile
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[1] / ".github" / "scripts" / "check-skills.py"


def load_checker():
    spec = importlib.util.spec_from_file_location("check_skills_under_test", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def make_tree(tmp: Path, skills: list[str], docs: dict[str, str]) -> None:
    for name in skills:
        d = tmp / "skills" / name
        d.mkdir(parents=True)
        (d / "SKILL.md").write_text(
            f"---\nname: {name}\ndescription: A sufficiently long description for {name}.\n---\nbody\n"
        )
    (tmp / ".agents" / "skills").mkdir(parents=True, exist_ok=True)
    for rel, body in docs.items():
        path = tmp / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(body)


def with_tree(skills, docs):
    """Context manager: a temp repo with the checker's paths pointed at it."""
    class _Ctx:
        def __enter__(self):
            self.tmp = tempfile.TemporaryDirectory()
            root = Path(self.tmp.name)
            make_tree(root, skills, docs)
            self.checker = load_checker()
            self.checker.REPO_ROOT = root
            self.checker.SKILLS_DIR = root / "skills"
            self.checker.AGENTS_SKILLS_DIR = root / ".agents" / "skills"
            return self.checker

        def __exit__(self, *exc):
            self.tmp.cleanup()

    return _Ctx()


def test_phantom_citation_is_caught() -> None:
    docs = {"AGENTS.md": "See `skills/does-not-exist/SKILL.md` for details.\n"}
    with with_tree(["real-skill"], docs) as c:
        problems = c.check_citations()
    assert len(problems) == 1, problems
    assert "does-not-exist" in problems[0]
    assert "AGENTS.md:1" in problems[0]


def test_tilde_agents_path_is_caught() -> None:
    """The exact shape that survived four documents: `~/.agents/skills/<x>/...`."""
    docs = {"AGENTS.md": "Located at `~/.agents/skills/phantom-pipeline/SKILL.md`.\n"}
    with with_tree(["real-skill"], docs) as c:
        problems = c.check_citations()
    assert len(problems) == 1, problems
    assert "phantom-pipeline" in problems[0]


def test_existing_citation_passes() -> None:
    docs = {"AGENTS.md": "See `skills/real-skill/SKILL.md`.\n"}
    with with_tree(["real-skill"], docs) as c:
        assert c.check_citations() == []


def test_stale_count_is_caught() -> None:
    docs = {"README.md": "There are 10 conceptual skill SKILL.md files here.\n"}
    with with_tree(["a", "b", "c"], docs) as c:
        problems = c.check_citations()
    assert len(problems) == 1, problems
    assert "10" in problems[0] and "3" in problems[0]


def test_correct_count_passes() -> None:
    docs = {"README.md": "There are 3 skill SKILL.md files here.\n"}
    with with_tree(["a", "b", "c"], docs) as c:
        assert c.check_citations() == []


def test_template_placeholder_is_not_a_citation() -> None:
    """`skills/<name>/SKILL.md` describes a shape; it names no skill."""
    docs = {"CONTRIBUTING.md": "Every skill is `skills/<name>/SKILL.md` on disk.\n"}
    with with_tree(["a"], docs) as c:
        assert c.check_citations() == []


def test_glob_is_not_a_citation() -> None:
    docs = {"README.md": "Discovered via `skills/*/SKILL.md`.\n"}
    with with_tree(["a"], docs) as c:
        assert c.check_citations() == []


def test_url_is_not_a_citation() -> None:
    """A lobehub/GitHub slug in prose is not a claim about this repo."""
    docs = {"AGENTS.md": "| https://lobehub.com/skills/some-publisher-skill | ok |\n"}
    with with_tree(["a"], docs) as c:
        assert c.check_citations() == []


def test_ignore_marker_opts_out() -> None:
    """Documentation *of* a defect must be able to name the defect."""
    docs = {"FINDING.md": "`skills/gone/SKILL.md` was removed. <!-- skills-ignore -->\n"}
    with with_tree(["a"], docs) as c:
        assert c.check_citations() == []


def test_vendored_agents_skill_counts_as_existing() -> None:
    docs = {"README.md": "See `.agents/skills/vendored-one/SKILL.md`.\n"}
    with with_tree(["a"], docs) as c:
        (c.AGENTS_SKILLS_DIR / "vendored-one").mkdir(parents=True)
        (c.AGENTS_SKILLS_DIR / "vendored-one" / "SKILL.md").write_text("---\nname: v\n---\n")
        assert c.check_citations() == []


def main() -> int:
    tests = [(n, f) for n, f in sorted(globals().items()) if n.startswith("test_") and callable(f)]
    failures = 0
    for name, fn in tests:
        try:
            fn()
            print(f"PASS: {name}")
        except AssertionError as exc:
            failures += 1
            print(f"FAIL: {name}: {exc}")
        except Exception as exc:  # a crash is a failure, not a skip
            failures += 1
            print(f"FAIL: {name}: raised {type(exc).__name__}: {exc}")
    print()
    if failures:
        print(f"FAILED: {failures} of {len(tests)} self-test(s)")
        return 1
    print(f"PASSED: {len(tests)} self-test(s)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
