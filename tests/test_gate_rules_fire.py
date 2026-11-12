#!/usr/bin/env python3
"""Probes for rules that were declared without a test proving they fire.

`AGENTS.md` lists 24 rules across 7 gates. Before this file, 0 of them named a
test: the declarations said what each rule protects, and nothing demonstrated
that the rule actually fires. That is the same gap the audit found twice — a
claim written down and trusted.

Each test below breaks something on purpose and asserts the gate reports it, or
asserts the gate's own predicate accepts what it should. Where a gate can only be
exercised by running it (shell + subprocess), the test writes a real file into
the tree and removes it.

Run: python tests/test_gate_rules_fire.py
"""
from __future__ import annotations

import importlib.util
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]


def _load(name: str, rel: str):
    spec = importlib.util.spec_from_file_location(name, REPO / rel)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


gen_arch = _load("gate_rules_gen_arch", "scripts/gen-architecture.py")
check_skills = _load("gate_rules_check_skills", ".github/scripts/check-skills.py")
check_swallows = _load("gate_rules_check_swallows", ".github/scripts/check-swallows.py")


def run_ci_check() -> int:
    proc = subprocess.run(["bash", str(REPO / ".github" / "scripts" / "ci-check.sh")],
                          cwd=REPO, capture_output=True, text=True)
    return proc.returncode


def with_repo_file(name: str, body: str) -> int:
    path = REPO / name
    if path.exists():
        raise AssertionError(f"refusing to overwrite {name}")
    path.write_text(body, encoding="utf-8")
    try:
        return run_ci_check()
    finally:
        path.unlink()


# ── protocol-escalation-justified (ci-check.sh) ────────────────────────────
def test_unjustified_escalation_fires() -> None:
    # no-escalation: this line is a fixture string, not a call site
    body = 'def go(c):\n    return c.request("u", protocol="ja3")\n'
    assert with_repo_file("_probe_escalation_bare.py", body) == 1


def test_justified_escalation_passes() -> None:
    body = (
        "def go(c):\n"
        "    # Why not HTTP/1.1: Cloudflare fingerprints TLS; tested latency 12ms.\n"
        '    return c.request("u", protocol="ja3")\n'
    )
    assert with_repo_file("_probe_escalation_ok.py", body) == 0


# ── skill-frontmatter-valid (check-skills.py) ──────────────────────────────
def _skill_dir(tmp: Path, name: str, frontmatter: str) -> Path:
    d = tmp / "skills" / name
    d.mkdir(parents=True)
    (d / "SKILL.md").write_text(frontmatter, encoding="utf-8")
    return d


def test_missing_frontmatter_fires() -> None:
    import tempfile
    with tempfile.TemporaryDirectory() as tmp:
        d = _skill_dir(Path(tmp), "no-front", "just a body, no ---\n")
        old = check_skills.SKILLS_DIR
        check_skills.SKILLS_DIR = Path(tmp) / "skills"
        try:
            problems = check_skills.check_skill(d)
        finally:
            check_skills.SKILLS_DIR = old
    assert any("frontmatter" in p for p in problems), problems


def test_non_kebab_name_fires() -> None:
    import tempfile
    with tempfile.TemporaryDirectory() as tmp:
        d = _skill_dir(Path(tmp), "BadName",
                       "---\nname: BadName\ndescription: "
                       "A description that is long enough to pass.\n---\nbody\n")
        old = check_skills.SKILLS_DIR
        check_skills.SKILLS_DIR = Path(tmp) / "skills"
        try:
            problems = check_skills.check_skill(d)
        finally:
            check_skills.SKILLS_DIR = old
    assert any("kebab-case" in p for p in problems), problems


def test_short_description_fires() -> None:
    import tempfile
    with tempfile.TemporaryDirectory() as tmp:
        d = _skill_dir(Path(tmp), "short-desc",
                       "---\nname: short-desc\ndescription: too short\n---\nbody\n")
        old = check_skills.SKILLS_DIR
        check_skills.SKILLS_DIR = Path(tmp) / "skills"
        try:
            problems = check_skills.check_skill(d)
        finally:
            check_skills.SKILLS_DIR = old
    assert any("description is" in p for p in problems), problems


# ── no-blanket-silent-except / narrow-handler-allowed (check-swallows.py) ──
def _violations(src: str, filename: str = "target.py"):
    """Violations only: check-swallows returns (violations, notes)."""
    import tempfile
    with tempfile.TemporaryDirectory() as tmp:
        path = REPO / filename
        if path.exists():
            raise AssertionError(f"refusing to overwrite {filename}")
        path.write_text(src, encoding="utf-8")
        try:
            violations, _notes = check_swallows.scan(path)
        finally:
            path.unlink()
        return violations


def test_blanket_silent_except_fires() -> None:
    problems = _violations(
        "def f():\n"
        "    try:\n"
        "        return 1\n"
        "    except Exception:\n"
        "        pass\n"
    )
    assert problems, "a silent `except Exception: pass` was not reported"


def test_narrow_silent_handler_is_allowed() -> None:
    problems = _violations(
        "def f():\n"
        "    try:\n"
        "        return int('x')\n"
        "    except ValueError:\n"
        "        pass\n"
    )
    assert not problems, f"narrow silence was reported as a violation: {problems}"


def test_logged_blanket_handler_passes() -> None:
    problems = _violations(
        "import logging\n"
        "log = logging.getLogger(__name__)\n"
        "def f():\n"
        "    try:\n"
        "        return 1\n"
        "    except Exception:\n"
        "        log.warning('failed')\n"
    )
    assert not problems, f"a logged blanket handler was flagged: {problems}"


# ── dict-chosen-protocol-declared (check-swallows.py) ──────────────────────
def test_dict_chosen_protocol_fires() -> None:
    """`scan()` only sees `protocol=` keywords; dict literals are a separate pass."""
    import tempfile
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        path = root / "t.py"
        path.write_text('CONFIG = {"protocol": "ja3"}\n', encoding="utf-8")
        original_root = check_swallows.ROOT
        check_swallows.ROOT = root
        try:
            problems = check_swallows.scan_dict_protocols(path)
        finally:
            check_swallows.ROOT = original_root
    assert problems, "a protocol chosen through a dict was not reported"


# ── layer-edges-downward (gen-architecture.py) ─────────────────────────────
def _layer_pair() -> tuple[str, str]:
    layers = gen_arch.MODULE_LAYER
    lower = next(m for m, lay in layers.items() if lay == 1)
    higher = next(m for m, lay in layers.items() if lay == 4)
    return lower, higher


def _upward_problems(edges: dict[str, set[str]]) -> list[str]:
    """Run build() against a synthetic import graph."""
    lower, higher = _layer_pair()
    original = gen_arch.imports_of
    original_discover = gen_arch.discover
    gen_arch.discover = lambda: {m: REPO / "_synthetic.py" for m in (lower, higher)}
    gen_arch.imports_of = lambda path, known: set(edges.get(path.stem, set())) | {
        d for m, deps in edges.items() for d in deps if m == _name_of(path)
    }
    try:
        _rendered, problems = gen_arch.build()
    finally:
        gen_arch.imports_of = original
        gen_arch.discover = original_discover
    return problems


def _name_of(path: Path) -> str:
    return path.stem


def _run_build_with_edges(target: str) -> list[str]:
    """Run build() against a synthetic graph: `target` is imported by the other.

    discover() is patched to two real temp files because build() also opens the
    paths it discovered; a fake path raises FileNotFoundError.
    """
    import tempfile

    lower, higher = _layer_pair()
    with tempfile.TemporaryDirectory() as tmp:
        stub = Path(tmp) / "_s.py"
        stub.write_text("", encoding="utf-8")
        original_imports = gen_arch.imports_of
        original_discover = gen_arch.discover
        original_root = gen_arch.ROOT
        gen_arch.ROOT = Path(tmp)
        gen_arch.discover = lambda: {lower: stub, higher: stub}
        gen_arch.imports_of = lambda path, known: set([target])
        try:
            _rendered, problems = gen_arch.build()
        finally:
            gen_arch.imports_of = original_imports
            gen_arch.discover = original_discover
            gen_arch.ROOT = original_root
        return problems


def test_upward_edge_is_detected() -> None:
    """L1 importing L4 is the violation the layer check exists for."""
    _lower, higher = _layer_pair()
    problems = _run_build_with_edges(higher)
    assert any("upward edge" in p for p in problems), problems


def test_downward_edge_is_allowed() -> None:
    _lower, _higher = _layer_pair()
    problems = _run_build_with_edges(_lower)
    assert not any("upward edge" in p for p in problems), problems


# ── line arithmetic near the top of a file ─────────────────────────────────
# ci-check.sh computed a negative sed window for escalations on line <= 5,
# which sed parsed as an option: justified escalations scored 0/4 and blocked
# merges. check-swallows.py computes the same kind of window, so its near-top
# behaviour is pinned here rather than assumed.
def _swallow_case(src: str) -> int:
    import tempfile
    original_root = check_swallows.ROOT
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        check_swallows.ROOT = root
        path = root / "t.py"
        path.write_text(src, encoding="utf-8")
        try:
            return len(check_swallows.scan(path)[0])
        finally:
            check_swallows.ROOT = original_root


def test_marker_on_except_line_near_top_passes() -> None:
    src = "try:\n    x = 1\nexcept Exception:  # swallow: deliberate\n    pass\n"
    assert _swallow_case(src) == 0


def test_marker_inside_handler_near_top_passes() -> None:
    src = "try:\n    x = 1\nexcept Exception:\n    # swallow: deliberate\n    pass\n"
    assert _swallow_case(src) == 0


def test_blanket_except_at_line_two_still_fires() -> None:
    src = "try:\n    x = 1\nexcept Exception:\n    pass\n"
    assert _swallow_case(src) == 1


def main() -> int:
    tests = [(n, f) for n, f in sorted(globals().items())
             if n.startswith("test_") and callable(f)]
    failures = 0
    for name, fn in tests:
        try:
            fn()
            print(f"PASS: {name}")
        except AssertionError as exc:
            failures += 1
            print(f"FAIL: {name}: {exc}")
        except Exception as exc:
            failures += 1
            print(f"FAIL: {name}: raised {type(exc).__name__}: {exc}")
    print()
    if failures:
        print(f"FAILED: {failures} of {len(tests)} probe(s)")
        return 1
    print(f"PASSED: {len(tests)} probe(s)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
