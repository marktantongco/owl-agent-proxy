#!/usr/bin/env python3
"""Self-tests for the credential rule in .github/scripts/ci-check.sh.

The rule claimed "no hardcoded user:password@ proxy URL anywhere in the tree"
while scanning four extensions and skipping any path containing `test_`. Probed:
a credential in a `.sh` or `.yml` file passed clean. These tests pin the widened
scope so it cannot quietly narrow again — the regression is not "a bug was
fixed", it is "the guard stopped covering what its description says".

Each case writes a file into the real tree, runs the real script, and removes it.

Run: python tests/test_ci_check_credentials.py
"""
from __future__ import annotations

import subprocess
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
SCRIPT = REPO / ".github" / "scripts" / "ci-check.sh"

# A credential shaped like a real leak: no placeholder token, no example domain.
LEAK = "http://bob:hunter2@10.0.0.1:3128"  # cred-ok: the leak fixture these tests feed the rule


def run_check() -> int:
    proc = subprocess.run(["bash", str(SCRIPT)], cwd=REPO, capture_output=True, text=True)
    return proc.returncode


def with_file(name: str, body: str) -> int:
    path = REPO / name
    if path.exists():
        raise AssertionError(f"refusing to overwrite {name}; test file name collides")
    path.write_text(body, encoding="utf-8")
    try:
        return run_check()
    finally:
        path.unlink()


# ── must be caught ─────────────────────────────────────────────────────────
def test_python_leak_caught() -> None:
    assert with_file("_probe_cred_a.py", f'P = "{LEAK}"\n') == 1


def test_shell_leak_caught() -> None:
    """The original gap: .sh was never scanned."""
    assert with_file("_probe_cred_b.sh", f'export P="{LEAK}"\n') == 1


def test_yaml_leak_caught() -> None:
    """The original gap: .yml was never scanned."""
    assert with_file("_probe_cred_c.yml", f'proxy: "{LEAK}"\n') == 1


def test_toml_leak_caught() -> None:
    assert with_file("_probe_cred_d.toml", f'proxy = "{LEAK}"\n') == 1


def test_javascript_leak_caught() -> None:
    assert with_file("_probe_cred_e.js", f'const p = "{LEAK}"\n') == 1


def test_leak_in_test_named_file_is_caught() -> None:
    """`grep -v test_` used to exempt this. Tests are not a safe place for secrets."""
    assert with_file("_probe_test_cred.py", f'P = "{LEAK}"\n') == 1


# ── must be ignored ────────────────────────────────────────────────────────
def test_placeholder_username_ignored() -> None:
    body = 'P = "http://YOUR_USERNAME:YOUR_PASSWORD@p.webshare.io:80"\n'
    assert with_file("_probe_ok_a.py", body) == 0


def test_example_domain_ignored() -> None:
    assert with_file("_probe_ok_b.py", 'P = "http://user1:pass1@proxy.example.com:8080"\n') == 0


def test_localhost_ignored() -> None:
    assert with_file("_probe_ok_c.py", 'P = "http://dev:dev@localhost:8080"\n') == 0


def test_inline_cred_ok_marker_ignored() -> None:
    assert with_file("_probe_ok_d.py", f'P = "{LEAK}"  # cred-ok: fixture\n') == 0


def test_cred_ok_on_preceding_line_ignored() -> None:
    """The detector's own pattern needs this form: the marker cannot share the line."""
    assert with_file("_probe_ok_e.py", f'# cred-ok: fixture\nP = "{LEAK}"\n') == 0


def test_clean_tree_passes() -> None:
    assert run_check() == 0


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
    sys.exit(main())
