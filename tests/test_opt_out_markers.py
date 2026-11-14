#!/usr/bin/env python3
"""Probes for the three self-exemption markers.

Each gate defines a rule, and each gate ships a way to be exempted from that
rule:

    # swallow:       <reason>   check-swallows.py
    # cred-ok:       <reason>   ci-check.sh CHECK 2
    # no-escalation: <reason>   ci-check.sh CHECK 1

All three are documented as requiring a reason. As of this file, all three
enforce it: a bare marker used to exempt, which is not a justification but a
switch that turns the rule off, and the person who hits the rule first is the
person holding the switch.

These probes measure what each marker actually accepts. They are deliberately
adversarial: the question is not "does the marker work", it is "what is the
cheapest thing that works".

Run: python tests/test_opt_out_markers.py
"""
from __future__ import annotations

import importlib.util
import re
import subprocess
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
CI_CHECK = REPO / ".github" / "scripts" / "ci-check.sh"

_ESCALATION = 'CLIENT = build(protocol="ja3")  # no-escalation: PLACEHOLDER'
# cred-ok: fake credential fed to CHECK 2 by the probes below
_CREDENTIAL = 'CRED = "https://bob:hunter2@10.9.9.9:3128"'


def _load_swallows():
    spec = importlib.util.spec_from_file_location(
        "check_swallows_under_test", REPO / ".github" / "scripts" / "check-swallows.py"
    )
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def swallow_violations(src: str) -> int:
    module = _load_swallows()
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        module.ROOT = root
        path = root / "t.py"
        path.write_text(src, encoding="utf-8")
        try:
            return len(module.scan(path)[0])
        finally:
            module.ROOT = REPO


def ci_verdict(lines: list[str]) -> str:
    """Run ci-check.sh over a temp tree and return the verdict for probe.py."""
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        (root / "probe.py").write_text("\n".join(lines) + "\n", encoding="utf-8")
        out = subprocess.run(
            ["bash", str(CI_CHECK)], cwd=root, capture_output=True, text=True
        ).stdout
    match = re.search(r"probe\.py:\d+ — ([^\n]+)", out)
    if match:
        return match.group(1).strip()
    return "Hardcoded credentials" if "Hardcoded credentials" in out else "NOT REPORTED"


# ── check-swallows.py: # swallow: ──────────────────────────────────────────
def test_swallow_marker_is_required_for_a_broad_handler() -> None:
    assert swallow_violations("try:\n    x = 1\nexcept Exception:\n    pass\n") == 1


def test_swallow_marker_with_a_reason_exempts() -> None:
    src = "try:\n    x = 1\nexcept Exception:  # swallow: shutdown path\n    pass\n"
    assert swallow_violations(src) == 0


def test_swallow_marker_cannot_borrow_a_neighbours_reason() -> None:
    """A marker on the narrow handler above must not cover the broad one below."""
    src = (
        "try:\n    a = 1\n"
        "except ValueError:  # swallow: reason for the narrow one only\n    pass\n"
        "except Exception:\n    pass\n"
    )
    assert swallow_violations(src) == 1


def test_swallow_marker_without_a_reason_does_not_exempt() -> None:
    """A bare `# swallow:` used to exempt. It now has to name a reason."""
    src = "try:\n    x = 1\nexcept Exception:  # swallow:\n    pass\n"
    assert swallow_violations(src) == 1


def test_swallow_dict_protocol_marker_requires_a_reason() -> None:
    """The dict-protocol path in check-swallows.py was missed by the reason fix.

    `scan_dict_protocols` tested `"# no-escalation:" in context`, so a bare
    marker exempted a dict-chosen protocol even after the same marker was
    tightened everywhere else. Found by auditing this repo's own gates rather
    than by a test.
    """
    module = _load_swallows()
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        module.ROOT = root
        path = root / "t.py"
        try:
            path.write_text('C = {"protocol": "ja3"}  # no-escalation:\n', encoding="utf-8")
            bare = len(module.scan_dict_protocols(path))
            path.write_text('C = {"protocol": "ja3"}  # no-escalation: fixture\n', encoding="utf-8")
            with_reason = len(module.scan_dict_protocols(path))
        finally:
            module.ROOT = REPO
    assert bare == 1, "bare marker still exempts a dict-chosen protocol"
    assert with_reason == 0, "a reason no longer exempts"


# ── ci-check.sh CHECK 2: # cred-ok: ────────────────────────────────────────
def test_cred_ok_required_for_a_hardcoded_credential() -> None:
    assert ci_verdict([_CREDENTIAL]) == "Hardcoded credentials"


def test_cred_ok_with_a_reason_exempts() -> None:
    got = ci_verdict([_CREDENTIAL + "  # cred-ok: fixture"])
    assert got == "opted out (cred-ok)", got


def test_cred_ok_without_a_reason_does_not_exempt() -> None:
    """A bare `# cred-ok:` used to exempt. It now has to name a reason."""
    got = ci_verdict([_CREDENTIAL + "  # cred-ok:"])
    assert got == "Hardcoded credentials", got


def test_cred_ok_is_scoped_to_the_next_line() -> None:
    """Two lines above is too far — the marker must sit on or directly above."""
    got = ci_verdict(["# cred-ok: unrelated note", "x = 1", _CREDENTIAL])
    assert got == "Hardcoded credentials", got


# ── ci-check.sh CHECK 1: # no-escalation: ──────────────────────────────────
def test_no_escalation_required_for_a_bare_escalation() -> None:
    got = ci_verdict([_ESCALATION.replace("  # no-escalation: PLACEHOLDER", "")])
    assert got.startswith("Missing justification"), got


def test_no_escalation_with_a_reason_exempts() -> None:
    got = ci_verdict([_ESCALATION.replace("PLACEHOLDER", "fixture for the probes")])
    assert got == "opted out inline", got


def test_no_escalation_without_a_reason_does_not_exempt() -> None:
    """A bare `# no-escalation:` used to exempt. It now has to name a reason."""
    got = ci_verdict([_ESCALATION.replace("PLACEHOLDER", "")])
    assert got.startswith("Missing justification"), got


def test_no_escalation_is_scoped_to_the_line_above() -> None:
    """Same reach as CHECK 2's `# cred-ok:`: the line, or the line above.

    It used to reach five lines up, because CHECK 1 tested the opt-out against
    the five-line justification window. A marker written about one line could
    therefore exempt a different one four lines later. Two CHECKs, two rules,
    one reach.
    """
    lines = ["# no-escalation: reason", _ESCALATION.replace("  # no-escalation: PLACEHOLDER", "")]
    assert ci_verdict(lines) == "opted out inline"


def test_no_escalation_does_not_reach_two_lines_up() -> None:
    """A marker about a different line must not exempt this one."""
    lines = ["# no-escalation: reason", "x = 1",
             _ESCALATION.replace("  # no-escalation: PLACEHOLDER", "")]
    got = ci_verdict(lines)
    assert got.startswith("Missing justification"), got


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
