"""Tests for scripts/gen-architecture.py — the layer-drift detector.

A checker that never fails is worse than no checker: the README claimed 484
passing tests while CI was red for three days. These tests prove the detector
actually detects, by building throwaway trees with known defects.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

# The file name has a hyphen, so it cannot be imported by name.
_spec = importlib.util.spec_from_file_location(
    "gen_architecture", REPO_ROOT / "scripts" / "gen-architecture.py"
)
gen = importlib.util.module_from_spec(_spec)
assert _spec.loader is not None
_spec.loader.exec_module(gen)


def _write(root: Path, rel: str, body: str) -> Path:
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(body, encoding="utf-8")
    return path


def test_imports_of_resolves_top_level_and_relative() -> None:
    """`from router import X` must resolve to gateway.router, not to nothing."""
    known = {"gateway.router", "gateway.app", "proxy_defense"}
    path = _write(
        Path(__file__).parent / "_tmp_arch",
        "gateway/app.py",
        "from __future__ import annotations\n"
        "from router import Router\n"
        "from .free_catalog import loader\n"
        "import proxy_defense\n",
    )
    try:
        found = gen.imports_of(path, known)
    finally:
        path.unlink()
        path.parent.rmdir()

    assert "gateway.router" in found, found
    assert "proxy_defense" in found, found


def test_imports_of_ignores_third_party_and_self() -> None:
    known = {"proxy_defense", "proxy_harvester"}
    path = _write(
        Path(__file__).parent / "_tmp_arch",
        "proxy_defense.py",
        "import asyncio\nimport httpx\nimport proxy_harvester\n",
    )
    try:
        found = gen.imports_of(path, known)
    finally:
        path.unlink()
        path.parent.rmdir()

    assert found == {"proxy_harvester"}, found


def test_cycle_detection_finds_a_two_node_cycle() -> None:
    graph = {"a": {"b"}, "b": {"a"}, "c": set()}
    found = gen.cycles(graph)
    assert found == [["a", "b"]], found


def test_cycle_detection_is_empty_for_a_dag() -> None:
    graph = {"a": {"b"}, "b": {"c"}, "c": set()}
    assert gen.cycles(graph) == []


def test_committed_map_is_current_and_layers_hold() -> None:
    """The real tree must match the committed map with no structural problems."""
    rendered, problems = gen.build()
    committed = (REPO_ROOT / "docs" / "architecture" / "MODULE_GRAPH.md").read_text(encoding="utf-8")

    assert problems == [], problems
    assert rendered == committed, (
        "docs/architecture/MODULE_GRAPH.md is stale — "
        "run: python scripts/gen-architecture.py"
    )


def test_every_shipped_module_is_mapped_to_a_layer() -> None:
    """A new top-level module must be added to LAYERS/EDGE_NOTES, not slip in."""
    modules = gen.discover()
    unmapped = sorted(set(modules) - set(gen.MODULE_LAYER))
    assert unmapped == [], f"unmapped modules: {unmapped}"


def _run_as_script() -> int:
    """Run every test function without pytest.

    `python -m unittest tests.test_architecture_check` collects **zero** tests
    from this file (plain functions, no TestCase) and still exits 0 — a green
    light that proves nothing. This runner is what CI calls instead.
    """
    failures = 0
    tests = [(name, obj) for name, obj in sorted(globals().items())
             if name.startswith("test_") and callable(obj)]
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
