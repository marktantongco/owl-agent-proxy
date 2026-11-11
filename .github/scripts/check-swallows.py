#!/usr/bin/env python3
"""Fail the build when a broad exception handler swallows an error silently.

A handler is *silent* when its body does nothing but ``pass``, ``continue``,
``break``, or ``return`` (bare / ``None`` / a constant). Silence on a narrow,
self-evident exception (``ValueError`` while validating a free-proxy line) is a
legitimate parser pattern, so those are reported but allowed.

What is never allowed is silence on a **blanket** handler — ``except Exception``
or a bare ``except:``. That is where real bugs hide: the pool reports zero
proxies, the caller sees ``null``, and nothing anywhere says why. Such handlers
must either log, or carry an explicit ``# swallow: <reason>`` comment stating why
silence is correct here.

The second check covers the "swallowed capability" case that ``ci-check.sh``
cannot see: it only matches an explicit keyword escalation (``protocol=` plus a
quoted escalated value on the same line), so a protocol chosen through a
dict — ``CONFIG = {"protocol": "browser"}`` or ``**params`` — escalates silently
and passes the escalation guard. Any literal dict value that is an escalated
protocol is reported here unless it carries the same ``# swallow: <reason>``
marker or a ``# no-escalation: <reason>`` note.

A guard that can be walked around by changing a keyword argument to a dict is
not a guard; it is a formality.

Stdlib only. Exit 0 clean, 1 violations.

Rules enforced — see scripts/gen-docs.py for the `gate:` convention:

gate: no-blanket-silent-except: except Exception / bare except never swallows silently [required]
gate: dict-chosen-protocol-declared: a protocol literal reaching a dict is reported like a keyword call [required]
gate: narrow-handler-allowed: silence on a specific exception is reported but permitted
"""

from __future__ import annotations

import ast
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
MARKER = "# swallow:"
BROAD = {"Exception", "BaseException"}


def _is_constant_value(node: ast.Return) -> bool:
    """True when a return yields nothing informative: bare, None, or a literal."""
    if node.value is None:
        return True
    if isinstance(node.value, ast.Constant):
        return True
    return False


def is_silent(handler: ast.ExceptHandler) -> bool:
    body = [stmt for stmt in handler.body]
    if not body:
        return True
    return all(
        isinstance(stmt, (ast.Pass, ast.Continue, ast.Break))
        or (isinstance(stmt, ast.Return) and _is_constant_value(stmt))
        for stmt in body
    )


def handler_type(handler: ast.ExceptHandler) -> str:
    if handler.type is None:
        return "bare"
    return ast.unparse(handler.type)


def is_broad(handler: ast.ExceptHandler) -> bool:
    if handler.type is None:
        return True
    text = handler_type(handler)
    return any(name in text for name in BROAD)


def has_marker(lines: list[str], handler: ast.ExceptHandler) -> bool:
    start = handler.lineno - 1
    end = getattr(handler, "end_lineno", handler.lineno)
    # The comment may sit on the `except` line or anywhere inside the handler.
    return any(MARKER in lines[i] for i in range(start, min(end, len(lines))))


def scan(path: Path) -> tuple[list[str], list[str]]:
    source = path.read_text(encoding="utf-8")
    lines = source.splitlines()
    tree = ast.parse(source, filename=str(path))

    violations: list[str] = []
    notes: list[str] = []

    for node in ast.walk(tree):
        if not isinstance(node, ast.ExceptHandler) or not is_silent(node):
            continue

        kind = handler_type(node)
        rel = f"{path.relative_to(ROOT)}:{node.lineno}"

        if is_broad(node) and not has_marker(lines, node):
            violations.append(
                f"{rel}: silent 'except {kind}' — log the error or add '{MARKER} <reason>'"
            )
        else:
            notes.append(f"{rel}: silent 'except {kind}' (allowed)")

    return violations, notes


ESCALATED_PROTOCOLS = {"ja3", "browser", "stealth", "websocket", "http/2"}


def scan_dict_protocols(path: Path) -> list[str]:
    """Protocol values chosen via a dict literal, which ci-check.sh cannot see."""
    source = path.read_text(encoding="utf-8")
    lines = source.splitlines()
    tree = ast.parse(source, filename=str(path))
    violations: list[str] = []

    for node in ast.walk(tree):
        if not isinstance(node, ast.Dict):
            continue
        for key, value in zip(node.keys, node.values):
            if not isinstance(key, ast.Constant) or key.value != "protocol":
                continue
            if not isinstance(value, ast.Constant) or value.value not in ESCALATED_PROTOCOLS:
                continue
            start = max(0, node.lineno - 4)
            end = getattr(node, "end_lineno", node.lineno)
            context = "\n".join(lines[start:end])
            if MARKER in context or "# no-escalation:" in context:
                continue
            violations.append(
                f"{path.relative_to(ROOT)}:{value.lineno}: protocol chosen via dict "
                f"({value.value!r}) — the escalation guard cannot match this form. Add a "
                f"justification "
                f"beside it or '{MARKER} <reason>'"
            )
    return violations


def main() -> int:
    targets = sorted(
        p for p in list(ROOT.glob("*.py")) if not p.name.startswith("_")
    )
    if not targets:
        print("SKIP: no source modules found")
        return 0

    violations: list[str] = []
    notes: list[str] = []
    for path in targets:
        found, info = scan(path)
        violations.extend(found)
        notes.extend(info)
        violations.extend(scan_dict_protocols(path))

    for note in notes:
        print(f"INFO: {note}")
    print()
    if violations:
        print(f"FAILED: {len(violations)} unexplained silently-swallowed exception(s)")
        for violation in violations:
            print(f"  - {violation}")
        return 1

    print(f"PASSED: {len(notes)} narrow silent handler(s) allowed, "
          "0 broad handlers swallowing, 0 dict-chosen protocol escalations")
    return 0


if __name__ == "__main__":
    sys.exit(main())
