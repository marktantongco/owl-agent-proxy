"""Tests for scripts/verify-skills-lock.py.

The lock this suite guards replaced a lock that verified nothing: version 1's
hashes matched no upstream revision and no normalisation of the files, so it
reported agreement with the tree only because nobody ever checked it. These
tests assert that the new verifier fails when it should.

Network-free: every test points the verifier at a temporary lock and temporary
files, so CI does not depend on GitHub.
"""

from __future__ import annotations

import importlib.util
import json
import sys
import tempfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

_spec = importlib.util.spec_from_file_location(
    "verify_skills_lock", REPO_ROOT / "scripts" / "verify-skills-lock.py"
)
lockmod = importlib.util.module_from_spec(_spec)
assert _spec.loader is not None
_spec.loader.exec_module(lockmod)


def test_committed_lock_is_version_2() -> None:
    """Version 1 could not be verified; the file must not silently regress."""
    lock = json.loads((REPO_ROOT / "skills-lock.json").read_text(encoding="utf-8"))
    assert lock["version"] == 2, "skills-lock.json must use the verifiable format"


def test_every_entry_pins_a_commit_and_a_scoped_hash() -> None:
    lock = json.loads((REPO_ROOT / "skills-lock.json").read_text(encoding="utf-8"))
    for name, entry in lock["skills"].items():
        assert entry.get("upstreamCommit"), f"{name}: no upstreamCommit"
        assert len(entry["upstreamCommit"]) == 40, f"{name}: commit is not a full SHA"
        assert entry["contentHash"].startswith("sha256:"), f"{name}: hash is not scoped"
        assert entry["contentHashCovers"], f"{name}: does not say what the hash covers"
        assert (REPO_ROOT / entry["vendoredPath"]).is_file(), f"{name}: vendoredPath missing"


def test_offline_check_passes_for_the_committed_tree() -> None:
    lock = json.loads((REPO_ROOT / "skills-lock.json").read_text(encoding="utf-8"))
    assert lockmod.check_local(lock["skills"]) == []


def test_local_check_detects_a_modified_file() -> None:
    """The whole point: an edited vendored file must fail, not pass quietly."""
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        (root / "skills" / "demo").mkdir(parents=True)
        target = root / "skills" / "demo" / "SKILL.md"
        target.write_text("---\nname: demo\n---\n\nbody\n", encoding="utf-8")

        entry = {
            "source": "someone/demo",
            "skillPath": "SKILL.md",
            "upstreamCommit": "0" * 40,
            "vendoredPath": "skills/demo/SKILL.md",
            "contentHash": lockmod.sha256_file(target),
            "contentHashCovers": "raw file bytes",
        }

        original_root = lockmod.ROOT
        lockmod.ROOT = root
        try:
            assert lockmod.check_local({"demo": entry}) == []

            target.write_text(target.read_text() + "\ninjected\n", encoding="utf-8")
            problems = lockmod.check_local({"demo": entry})
            assert len(problems) == 1, problems
            assert "content hash mismatch" in problems[0], problems

            target.unlink()
            problems = lockmod.check_local({"demo": entry})
            assert "missing" in problems[0], problems
        finally:
            lockmod.ROOT = original_root


def test_body_of_strips_frontmatter() -> None:
    text = "---\nname: x\ndescription: y\n---\n\nreal body\n"
    assert lockmod.body_of(text).strip() == "real body"


def test_body_of_handles_a_file_with_no_frontmatter() -> None:
    assert lockmod.body_of("just text\n") == "just text\n"


def test_declared_local_modification_must_be_frontmatter_only() -> None:
    """A declared edit is acceptable for frontmatter, never for the body.

    This is the subtle failure: `localModification` is a licence to differ, so a
    body edit hiding behind it would ship unverified.
    """
    upstream = "---\nname: FreeUnlimited-websearch\n---\n\nupstream body\n"
    vendored_frontmatter_only = "---\nname: freeunlimited-websearch\n---\n\nupstream body\n"
    vendored_body_edit = "---\nname: freeunlimited-websearch\n---\n\nupstream body\nplus a line\n"

    assert lockmod.body_of(upstream) == lockmod.body_of(vendored_frontmatter_only)
    assert lockmod.body_of(upstream) != lockmod.body_of(vendored_body_edit)


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
