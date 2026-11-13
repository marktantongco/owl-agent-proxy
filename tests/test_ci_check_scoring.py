#!/usr/bin/env python3
"""Probes for CHECK 1's justification scoring.

`protocol-escalation-justified` claims an escalation is rejected unless
justified. The scoring that decides this was counting prose:

  * `ms` was unbounded, so systems, problems, items, params, terms, forms,
    claims and algorithms all scored a latency point.
  * `tested` was unbounded, so "untested" and "not tested" scored.
  * `approved` was unbounded and unguarded for negation, so "unapproved",
    "untested" and "not yet approved" scored an approval point. A comment
    saying a change was NOT approved justified it.

The case that made this a correctness bug rather than sloppiness: one genuine
signal plus ordinary prose scored 2/4. `WARN` does not fail the build, so the
prose turned a blocking 1/4 into a passing 2/4.

Each case below writes a two-line file into a temp directory, points a copy of
ci-check.sh at it, and reads the verdict. Nothing in the repo is touched.

Run: python tests/test_ci_check_scoring.py
"""
from __future__ import annotations

import re
import subprocess
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
SCRIPT = REPO / ".github" / "scripts" / "ci-check.sh"

# This file probes CHECK 1, so it must contain the very pattern CHECK 1 looks
# for. The line is a fixture written into a temp directory, never executed.
# no-escalation: fixture for the scoring probes below
_LINE = 'CLIENT = build(protocol="ja3")'


def verdict(comment: str) -> str:
    """Run CHECK 1 against one comment + one escalation. Returns the verdict word."""
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        (root / "probe.py").write_text(
            f"{comment}\n{_LINE}\n", encoding="utf-8"
        )
        # ci-check.sh scans `.`, so run it with cwd set to the temp tree. It
        # reports paths relative to cwd, which keeps the parse simple.
        out = subprocess.run(
            ["bash", str(SCRIPT)],
            cwd=root,
            capture_output=True,
            text=True,
        ).stdout

    match = re.search(r"probe\.py:\d+ — ([A-Za-z ]+)", out)
    assert match, f"CHECK 1 did not report on the probe file. Output was:\n{out}"
    return match.group(1).strip()


def test_bare_escalation_is_rejected() -> None:
    assert verdict("# nothing relevant here") == "Missing justification"


def test_ordinary_prose_earns_nothing() -> None:
    """Words containing 'ms' are not latency evidence."""
    for prose in (
        "# This assumes the upstream systems are fine.",
        "# Items and params are unchanged; terms and claims are handled by forms.",
        "# The algorithms module handles this.",
    ):
        assert verdict(prose) == "Missing justification", prose


def test_negations_do_not_count_as_approval() -> None:
    """A negation must not score, and the probe must fail if the guard is removed.

    A bare "Not yet approved." scores 1 at most either way, so it cannot detect
    a missing negation guard. Each case here pairs the negation with one genuine
    signal: with the guard, 1 point and a blocking verdict; without it, 2 points
    and a passing WARN. The second number is what makes this a probe.
    """
    for prose in (
        "# Not yet approved, but the HTTP/1.1 baseline is what we use.",
        "# Unapproved by precedent; HTTP/1.1 is the baseline.",
        "# Untested, though the HTTP/1.1 baseline is in place.",
        "# Not tested against HTTP/1.1.",
    ):
        got = verdict(prose)
        assert got == "Missing justification", f"{prose} -> {got}"


def test_one_signal_plus_prose_does_not_pass() -> None:
    """The regression this whole file exists for.

    '# Approved by ops; this assumes the systems are stable.' used to score 2/4
    and pass as a WARN, because 'assumes' and 'systems' matched `ms`.
    """
    got = verdict("# Approved by ops; this assumes the systems are stable.")
    assert got == "Missing justification", f"expected a blocking verdict, got {got}"


def test_genuine_justification_still_passes() -> None:
    got = verdict(
        "# Measured 40ms better than the HTTP/1.1 baseline; Cloudflare rejects "
        "the latter; approved by ops."
    )
    assert got == "Justified", got


def test_realistic_justification_passes_in_full() -> None:
    """The shape a real justification takes: one protocol, one signal, one reason."""
    got = verdict(
        "# http/1.1 is the baseline here and this follows an anti-bot challenge; "
        "the behaviour is tested."
    )
    assert got == "Justified", got


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
        print(f"FAILED: {failures} of {len(tests)} self-test(s)")
        return 1
    print(f"PASSED: {len(tests)} self-test(s)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
