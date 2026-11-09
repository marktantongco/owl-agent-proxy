"""Tests for scripts/gen-docs.py — the AGENTS.md table generator.

The generator is only useful if a stale table makes it fail. These tests plant
drift in a throwaway copy of the repository's inputs and assert the check
catches it, so a future "just regenerate it in the PR" cannot quietly turn the
CI step into a no-op.

Runs with pytest, or directly: `python tests/test_docs_generator.py`
"""

from __future__ import annotations

import importlib.util
import json
import shutil
import sys
import tempfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

_spec = importlib.util.spec_from_file_location("gen_docs", REPO_ROOT / "scripts" / "gen-docs.py")
gen = importlib.util.module_from_spec(_spec)
assert _spec.loader is not None
_spec.loader.exec_module(gen)


def _sandbox(tmp: Path) -> Path:
    """A minimal tree with just the inputs the generator reads."""
    (tmp / "skills").mkdir(parents=True)
    (tmp / "gateway" / "free_catalog").mkdir(parents=True)
    (tmp / "tests").mkdir(parents=True)
    return tmp


def test_skill_rows_read_frontmatter_stage() -> None:
    """`pipeline_stage` in SKILL.md wins over the fallback map."""
    with tempfile.TemporaryDirectory() as td:
        root = _sandbox(Path(td))
        skill = root / "skills" / "brand-new"
        skill.mkdir()
        (skill / "SKILL.md").write_text(
            "---\nname: brand-new\ndescription: " + "x" * 30
            + "\npipeline_stage: VERIFY\nsource: someone/repo\n---\n\n# body\n",
            encoding="utf-8",
        )
        original = gen.SKILLS
        gen.SKILLS = root / "skills"
        try:
            rows = gen.skill_rows()
        finally:
            gen.SKILLS = original

    assert rows == [("brand-new", "VERIFY", "someone/repo")], rows


def test_skill_rows_without_stage_falls_back_and_is_labelled() -> None:
    with tempfile.TemporaryDirectory() as td:
        root = _sandbox(Path(td))
        skill = root / "skills" / "unstaged"
        skill.mkdir()
        (skill / "SKILL.md").write_text(
            "---\nname: unstaged\ndescription: " + "y" * 30 + "\n---\n\n# body\n",
            encoding="utf-8",
        )
        original = gen.SKILLS
        gen.SKILLS = root / "skills"
        try:
            rows = gen.skill_rows()
        finally:
            gen.SKILLS = original

    assert rows[0][1] == "—", rows
    # An undeclared source must say so rather than inventing one.
    assert rows[0][2] == "not declared in SKILL.md", rows


def test_catalog_counts_come_from_the_file_not_from_prose() -> None:
    """A provider whose model count changes must change the rendered row."""
    with tempfile.TemporaryDirectory() as td:
        root = _sandbox(Path(td))
        catalog = root / "gateway" / "free_catalog" / "providers.json"
        catalog.write_text(json.dumps({
            "last_updated": "2026-01-01",
            "source": "test",
            "providers": [
                {"name": "Alpha", "category": "provider_api", "models": [
                    {"id": "a/1", "rate_limit": "10 RPM"},
                    {"id": "a/2", "rate_limit": "10 RPM"},
                ]},
                # A rate limit of "-" must fall through to the next informative one.
                {"name": "Beta", "category": "inference_provider", "models": [
                    {"id": "b/1", "rate_limit": "-"},
                    {"id": "b/2", "rate_limit": "5 RPM"},
                ]},
            ],
        }), encoding="utf-8")

        original = gen.CATALOG
        gen.CATALOG = catalog
        try:
            rendered = gen.render_catalog()
        finally:
            gen.CATALOG = original

    assert "| Alpha | provider_api | 2 | 10 RPM |" in rendered, rendered
    assert "| Beta | inference_provider | 2 | 5 RPM |" in rendered, rendered
    assert "2 providers, 4 models" in rendered, rendered


def test_collect_counts_fails_loudly_instead_of_returning_question_marks() -> None:
    """A degraded count must raise, not render `?` into the committed table.

    The CI job installs pytest but pytest.ini requires --cov. Without pytest-cov
    pytest exits with a usage error; the generator used to swallow that into a
    `?` for every file and then compare the degraded table against the real one.
    `-o addopts=` must neutralise the ini file. This test asserts the count is a
    real number for every test file, not the `?` fallback.
    """
    files = sorted((REPO_ROOT / "tests").glob("test_*.py"))
    counts = gen._collect_counts(files)
    assert set(counts) == {p.name for p in files}, "a test file produced no count"
    assert all(isinstance(n, int) and n > 0 for n in counts.values()), counts


def test_rewrite_keeps_text_outside_the_markers() -> None:
    text = (
        "before prose\n\n"
        "<!-- generated:tests -->\n\nSTALE\n\n<!-- /generated:tests -->\n\n"
        "after prose\n"
    )
    out = gen.rewrite(text, "tests", "<!-- generated:tests -->\n\nFRESH\n\n<!-- /generated:tests -->")
    assert "before prose" in out and "after prose" in out
    assert "FRESH" in out and "STALE" not in out


def test_rewrite_fails_loudly_when_a_marker_is_missing() -> None:
    """A missing marker must not silently produce a half-generated document."""
    try:
        gen.rewrite("no markers here\n", "tests", "x")
    except SystemExit as exc:
        assert "no '<!-- generated:tests " in str(exc), exc
    else:
        raise AssertionError("rewrite() accepted a document with no markers")


def test_agents_md_is_current() -> None:
    """The committed AGENTS.md must match what the generator would write.

    This is the CI gate. It does not rewrite anything.
    """
    original = gen.AGENTS.read_text(encoding="utf-8")
    updated = original
    for name, render in gen.BLOCKS.items():
        rendered = render()
        assert rendered, f"{name} renderer returned nothing"
        updated = gen.rewrite(updated, name, rendered)

    if updated != original:
        raise AssertionError(
            "AGENTS.md generated blocks are stale — run: python scripts/gen-docs.py"
        )


def test_generated_skills_block_lists_real_directories() -> None:
    """Every skill directory appears in the block, and nothing invented does."""
    rendered = gen.render_skills()
    real = {p.parent.name for p in (REPO_ROOT / "skills").glob("*/SKILL.md")}
    listed = {
        line.split("|")[1].strip().strip("`")
        for line in rendered.splitlines()
        if line.startswith("| `")
    }
    assert listed == real, f"listed-only={listed - real} real-only={real - listed}"


def _run_as_script() -> int:
    failures = 0
    tests = [(n, o) for n, o in sorted(globals().items()) if n.startswith("test_") and callable(o)]
    for name, fn in tests:
        try:
            fn()
        except Exception as exc:  # noqa: BLE001 - a failing test is the point
            failures += 1
            print(f"FAIL {name}: {type(exc).__name__}: {exc}")
        else:
            print(f"PASS {name}")
    print(f"\n{len(tests) - failures}/{len(tests)} passed")
    if not tests:
        print("FAIL: collected 0 tests — the runner is broken, not the code")
        return 1
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(_run_as_script())
