#!/usr/bin/env python3
"""Self-tests for the `gate:` rule-declaration block in scripts/gen-docs.py.

The block exists so that deleting a rule shows up as a generated-table diff
rather than an edit nobody reviews. These tests prove the renderer actually
behaves that way, including the cases where it must refuse to render at all.

Run: python tests/test_gate_declarations.py
"""
from __future__ import annotations

import importlib.util
import tempfile
from pathlib import Path

GEN_DOCS = Path(__file__).resolve().parents[1] / "scripts" / "gen-docs.py"


def load_generator():
    spec = importlib.util.spec_from_file_location("gen_docs_under_test", GEN_DOCS)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def with_gates(files: dict[str, str]):
    """Point the generator at a temp tree containing fake gate scripts."""

    class _Ctx:
        def __enter__(self):
            self.tmp = tempfile.TemporaryDirectory()
            root = Path(self.tmp.name)
            for rel, body in files.items():
                path = root / rel
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(body)
            self.gen = load_generator()
            self.gen.ROOT = root
            self.gen.GATES = tuple(sorted(files.items()))
            return self.gen

        def __exit__(self, *exc):
            self.tmp.cleanup()

    return _Ctx()


def test_declared_rules_are_parsed() -> None:
    with with_gates({"g.py": "# gate: a-rule: protects A [required]\n"}) as gen:
        assert gen.declared_rules(gen.ROOT / "g.py") == [("a-rule", "protects A", True)]


def test_shell_comment_form_is_parsed() -> None:
    with with_gates({"g.sh": "# gate: shell-rule: protects shell [required]\n"}) as gen:
        assert gen.declared_rules(gen.ROOT / "g.sh")[0][0] == "shell-rule"


def test_docstring_form_is_parsed() -> None:
    """Python gates declare inside the module docstring, with no leading '#'."""
    body = '#!/usr/bin/env python3\n"""Gate.\n\ngate: doc-rule: protects doc [required]\n"""\n'
    with with_gates({"g.py": body}) as gen:
        assert gen.declared_rules(gen.ROOT / "g.py")[0][0] == "doc-rule"


def test_missing_required_marker_is_advisory() -> None:
    with with_gates({"g.py": "# gate: soft-rule: permits something\n"}) as gen:
        assert gen.declared_rules(gen.ROOT / "g.py") == [("soft-rule", "permits something", False)]


def test_render_includes_every_rule() -> None:
    files = {"a.py": "# gate: alpha: protects A [required]\n",
             "b.py": "# gate: beta: protects B\n"}
    with with_gates(files) as gen:
        out = gen.render_gates()
    assert "alpha" in out and "beta" in out
    assert "_beta_" in out, "advisory rules are italicised so the split is visible"


def test_render_counts_required_and_advisory_separately() -> None:
    files = {"a.py": "# gate: hard: x [required]\n", "b.py": "# gate: soft: y\n"}
    with with_gates(files) as gen:
        out = gen.render_gates()
    assert "2 rules, 1 required" in out, out.splitlines()[0]


def test_undeclared_gate_refuses_to_render() -> None:
    """A gate with no rules is a gate nobody can review — fail, don't guess."""
    with with_gates({"a.py": "# nothing declared here\n"}) as gen:
        try:
            gen.render_gates()
        except SystemExit as exc:
            assert "no `# gate:` declaration" in str(exc)
            return
    raise AssertionError("render_gates accepted a gate with no declared rules")


def test_missing_gate_file_refuses_to_render() -> None:
    class _Ctx:
        def __enter__(self):
            self.tmp = tempfile.TemporaryDirectory()
            gen = load_generator()
            gen.ROOT = Path(self.tmp.name)
            gen.GATES = (("does-not-exist.py", "gone"),)
            return gen

        def __exit__(self, *exc):
            self.tmp.cleanup()

    with _Ctx() as gen:
        try:
            gen.render_gates()
        except SystemExit as exc:
            assert "registry lists it, file is missing" in str(exc)
            return
    raise AssertionError("render_gates accepted a registry entry with no file")


def test_removing_a_rule_changes_the_table() -> None:
    """The whole point: deletion is a diff, not a silent edit."""
    two = {"g.py": "# gate: kept: still here [required]\n# gate: dropped: about to vanish [required]\n"}
    one = {"g.py": "# gate: kept: still here [required]\n"}
    with with_gates(two) as gen:
        before = gen.render_gates()
    with with_gates(one) as gen:
        after = gen.render_gates()
    assert "dropped" in before and "dropped" not in after
    assert "1 rules, 1 required" in after.splitlines()[0]


def test_real_repository_gates_all_declare() -> None:
    """No temp tree: the actual gates in this checkout must render."""
    gen = load_generator()
    out = gen.render_gates()
    for rel, _purpose in gen.GATES:
        assert rel in out, f"{rel} is registered but absent from the rendered table"


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
        except Exception as exc:
            failures += 1
            print(f"FAIL: {name}: raised {type(exc).__name__}: {exc}")
    print()
    if failures:
        print(f"FAILED: {failures} of {len(tests)} self-test(s)")
        return 1
    print(f"PASSED: {len(tests)} self-test(s)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
