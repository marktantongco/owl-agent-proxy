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

Stdlib only. Exit 0 clean, 1 violations.
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

    for note in notes:
        print(f"INFO: {note}")
    print()
    if violations:
        print(f"FAILED: {len(violations)} unexplained silently-swallowed exception(s)")
        for violation in violations:
            print(f"  - {violation}")
        return 1

    print(f"PASSED: {len(notes)} narrow silent handler(s) allowed, 0 broad handler(s) swallowing")
    return 0


if __name__ == "__main__":
    sys.exit(main())
