#!/usr/bin/env python3
"""Probe for `lock-is-checkable`: does `--update` record a hash that verifies?

This is the rule's whole claim. Version 1 of `skills-lock.json` failed it — its
`computedHash` matched no upstream revision and no normalisation of one, so the
lock could not be checked at all despite looking authoritative. A rule that says
"--update must be able to record a verifiable hash" needs a test that runs
--update and then verifies the result, or it is describing an intention.

`update()` needs the network. Here the two network calls are replaced with
deterministic fakes, so the part under test is exactly the part that broke in v1:
what gets written into the lock file.

Run: python tests/test_skills_lock_update.py
"""
from __future__ import annotations

import importlib.util
import json
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]

_SKILL_TEXT = b"---\nname: demo\ndescription: A demo skill.\n---\n\nbody\n"
_COMMIT_SHA = "a" * 40


def load_lock_module(root: Path, lock_path: Path):
    spec = importlib.util.spec_from_file_location(
        "lockmod_under_test", REPO / "scripts" / "verify-skills-lock.py"
    )
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    module.ROOT = root
    module.LOCK = lock_path
    return module


def with_skill(upstream: bytes = _SKILL_TEXT):
    """A temp repo with one vendored skill and a lock pointing at it."""

    class _Ctx:
        def __enter__(self):
            self.tmp = tempfile.TemporaryDirectory()
            root = Path(self.tmp.name)
            skill = root / "skills" / "demo" / "SKILL.md"
            skill.parent.mkdir(parents=True)
            skill.write_bytes(_SKILL_TEXT)

            lock_path = root / "skills-lock.json"
            lock_path.write_text(json.dumps({
                "version": 2,
                "skills": {
                    "demo": {
                        "source": "someone/demo",
                        "skillPath": "SKILL.md",
                        # Deliberately wrong: --update must replace it.
                        "upstreamCommit": "b" * 40,
                        "contentHash": "sha256:" + "0" * 64,
                        "contentHashCovers": "raw file bytes",
                        "vendoredPath": "skills/demo/SKILL.md",
                    }
                },
            }, indent=2) + "\n", encoding="utf-8")

            self.module = load_lock_module(root, lock_path)
            # Fake the two network calls. `api` returns one commit; the fetch
            # returns the same bytes the vendored file holds, unless the caller
            # asks for `upstream`, which simulates a diverged local copy.
            self.module.api = lambda url: [{
                "sha": _COMMIT_SHA,
                "commit": {"committer": {"date": "2026-11-12T00:00:00Z"}},
            }]
            self.module.fetch_at_commit = lambda repo, path, ref: upstream
            return self

        def __exit__(self, *exc):
            self.tmp.cleanup()

    return _Ctx()


def test_update_records_a_hash_that_verifies() -> None:
    """The claim, end to end: run --update, then run the verifier on the result."""
    with with_skill() as ctx:
        assert ctx.module.update() == 0

        written = json.loads(ctx.module.LOCK.read_text(encoding="utf-8"))
        entry = written["skills"]["demo"]

        # The hash must equal what the file actually holds, not a stale constant.
        assert entry["contentHash"] == ctx.module.sha256_file(
            ctx.module.ROOT / "skills" / "demo" / "SKILL.md"
        ), "recorded hash does not describe the vendored bytes"

        # And the verifier must accept the lock it just wrote.
        assert ctx.module.check_local(written["skills"]) == []


def test_update_pins_the_commit_it_fetched() -> None:
    with with_skill() as ctx:
        assert ctx.module.update() == 0
        entry = json.loads(ctx.module.LOCK.read_text(encoding="utf-8"))["skills"]["demo"]
        assert entry["upstreamCommit"] == _COMMIT_SHA
        assert entry["upstreamCommitDate"] == "2026-11-12"


def test_update_clears_local_modification_when_identical() -> None:
    with with_skill() as ctx:
        lock = json.loads(ctx.module.LOCK.read_text(encoding="utf-8"))
        lock["skills"]["demo"]["localModification"] = "stale note"
        ctx.module.LOCK.write_text(json.dumps(lock), encoding="utf-8")

        assert ctx.module.update() == 0
        entry = json.loads(ctx.module.LOCK.read_text(encoding="utf-8"))["skills"]["demo"]
        assert "localModification" not in entry, entry


def test_update_keeps_local_modification_when_diverged() -> None:
    """A diverged vendored copy must not be silently blessed."""
    with with_skill(upstream=b"---\nname: demo\n---\n\nupstream body\n") as ctx:
        assert ctx.module.update() == 0
        entry = json.loads(ctx.module.LOCK.read_text(encoding="utf-8"))["skills"]["demo"]
        assert "localModification" in entry, entry


def test_update_output_is_verifiable_not_just_written() -> None:
    """The v1 failure: bytes on disk that look authoritative and verify against nothing."""
    with with_skill() as ctx:
        ctx.module.update()
        written = json.loads(ctx.module.LOCK.read_text(encoding="utf-8"))
        for name, entry in written["skills"].items():
            path = ctx.module.ROOT / entry["vendoredPath"]
            assert entry["contentHash"].startswith("sha256:"), entry
            assert entry["contentHash"].split(":", 1)[1] == ctx.module.sha256_file(path)[
                len("sha256:"):
            ], f"{name}: hash does not verify"


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
    raise SystemExit(main())
