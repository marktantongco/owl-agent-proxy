#!/usr/bin/env python3
"""Generate the as-is architecture map, or verify the documented one still holds.

The README describes a layered design. Nothing checked that the tree actually
had it, and the two drifted far enough apart that CI was red on `main` for
three days while the README advertised "0 failed". This script makes the tree
the source of truth:

    python scripts/gen-architecture.py            # write docs/architecture/MODULE_GRAPH.md
    python scripts/gen-architecture.py --check    # exit 1 if the file is stale

What it measures, all from the repository itself:

* modules and their sizes (top-level `*.py` plus `gateway/`)
* the real import graph, from `ast`, so comments and docstrings cannot lie
* layer assignment, from the documented layer table below
* violations: upward edges, import cycles, and any package that is not in the
  layer table at all (so a new top-level module cannot slip in unmapped)

Stdlib only, so CI needs no extra install.
"""

from __future__ import annotations

import argparse
import ast
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "docs" / "architecture" / "MODULE_GRAPH.md"

# Layer table. Lower number = lower layer. An edge may only point downward or
# sideways; pointing up is a violation.
LAYERS: dict[int, tuple[str, str]] = {
    1: ("Supply", "harvested inventory, validation, trust scoring"),
    2: ("Egress core", "cache, dedupe, rate limit, pool, protocol ladder"),
    3: ("Ingress", "optional HTTP entry points (reverse proxy, token plane)"),
    4: ("Agent surface", "MCP server + packaged skills"),
}

MODULE_LAYER: dict[str, int] = {
    "proxy_harvester": 1,
    "proxy_defense": 2,
    "reverse_proxy": 3,
    "gateway.app": 3,
    "gateway.auth": 3,
    "gateway.billing": 3,
    "gateway.cache": 3,
    "gateway.circuit_breaker": 3,
    "gateway.router": 3,
    "gateway.audit": 3,
    "gateway.free_catalog.loader": 3,
    "gateway.free_catalog.router_integration": 3,
    "mcp_proxy_server": 4,
}

# Rationale per known edge, printed next to it. An edge with no rationale is
# reported as UNEXPLAINED rather than failing the build: new edges are allowed,
# they just have to be looked at.
EDGE_NOTES: dict[tuple[str, str], str] = {
    ("proxy_defense", "proxy_harvester"): "lazy import inside the pool; keeps cold import fast",
    ("mcp_proxy_server", "proxy_defense"): "lazy import per tool call",
    ("mcp_proxy_server", "proxy_harvester"): "honeypot + validate_proxy tools",
    ("reverse_proxy", "proxy_defense"): "lazy import on first request",
    ("gateway.app", "gateway.auth"): "bearer-token dependency",
    ("gateway.app", "gateway.billing"): "budget gate",
    ("gateway.app", "gateway.cache"): "response cache",
    ("gateway.app", "gateway.circuit_breaker"): "per-provider breaker",
    ("gateway.app", "gateway.router"): "model routing",
    ("gateway.app", "gateway.free_catalog.router_integration"): "tier-1 catalog wiring",
    ("gateway.app", "gateway.audit"): "redacted audit logger (lazy import in app)",
    ("gateway.free_catalog.loader", "gateway.router"): "loader emits ModelRoute objects",
    ("gateway.free_catalog.router_integration", "gateway.router"): "wires catalog routes into the Router",
    ("gateway.router", "gateway.free_catalog.loader"): "vendored catalog",
    ("gateway.free_catalog.router_integration", "gateway.free_catalog.loader"): "vendored catalog",
}

# Packages that are deliberately not part of the layered import graph.
EXCLUDED_DIRS = {
    ".git", ".venv", "venv", "node_modules", "__pycache__", "build", "dist",
    ".pytest_cache", "htmlcov", "tests", "scripts", "skills", ".agents",
    ".claude", "docs", "examples", "packaging", "config",
}
# Vendored third-party trees are not ours to layer.
VENDOR_ROOTS = {"free_search"}


def module_name(path: Path) -> str:
    rel = path.relative_to(ROOT).with_suffix("")
    return ".".join(rel.parts)


def discover() -> dict[str, Path]:
    """Every first-party module that participates in the layer graph."""
    found: dict[str, Path] = {}
    for path in sorted(ROOT.rglob("*.py")):
        rel = path.relative_to(ROOT)
        if any(part in EXCLUDED_DIRS for part in rel.parts):
            continue
        if rel.parts[0] in VENDOR_ROOTS or any(p in VENDOR_ROOTS for p in rel.parts[:2]):
            continue
        if path.name == "__init__.py":
            continue
        name = module_name(path)
        # Only the shipped surface: top-level modules and the gateway package.
        if rel.parts[0] == "gateway" or len(rel.parts) == 1:
            found[name] = path
    return found


def imports_of(path: Path, known: set[str]) -> set[str]:
    """Real (AST-level) first-party imports, resolved to module names."""
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    target = module_name(path)
    package = target.rsplit(".", 1)[0] if "." in target else ""

    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            if node.level and package:  # relative import inside gateway/
                base = package.split(".")
                base = base[: len(base) - node.level + 1]
                mod = ".".join(base + ([node.module] if node.module else []))
            else:
                mod = node.module or ""
            names.add(mod)
            for alias in node.names:  # `from pkg import submodule`
                names.add(f"{mod}.{alias.name}" if mod else alias.name)

    resolved: set[str] = set()
    for name in names:
        if name in known:
            resolved.add(name)
            continue
        # `import proxy_defense` then `proxy_defense.ResilientClient` is covered
        # above; `from gateway import router` lands here.
        for candidate in known:
            if name.endswith("." + candidate) or candidate.endswith("." + name):
                if candidate == target:
                    continue
                resolved.add(candidate)
                break
    resolved.discard(target)
    return resolved


def cycles(graph: dict[str, set[str]]) -> list[list[str]]:
    """Tarjan SCCs, filtered to real cycles (size > 1, or self-loop)."""
    index: dict[str, int] = {}
    low: dict[str, int] = {}
    stack: list[str] = []
    on_stack: set[str] = set()
    out: list[list[str]] = []
    counter = [0]

    def strongconnect(v: str) -> None:
        index[v] = low[v] = counter[0]
        counter[0] += 1
        stack.append(v)
        on_stack.add(v)
        for w in sorted(graph.get(v, ())):
            if w not in index:
                strongconnect(w)
                low[v] = min(low[v], low[w])
            elif w in on_stack:
                low[v] = min(low[v], index[w])
        if low[v] == index[v]:
            scc: list[str] = []
            while True:
                w = stack.pop()
                on_stack.discard(w)
                scc.append(w)
                if w == v:
                    break
            if len(scc) > 1:
                out.append(sorted(scc))

    for v in sorted(graph):
        if v not in index:
            strongconnect(v)
    return out


def build() -> tuple[str, list[str]]:
    modules = discover()
    known = set(modules)
    graph = {name: imports_of(path, known) for name, path in modules.items()}

    problems: list[str] = []
    lines: list[str] = []
    add = lines.append

    add("# Module Graph — as generated from the tree")
    add("")
    add("> Generated by `scripts/gen-architecture.py`. Do not edit by hand;")
    add("> `python scripts/gen-architecture.py --check` fails CI when this is stale.")
    add("")

    add("## Layers")
    add("")
    add("| Layer | Name | Responsibility | Modules |")
    add("|-------|------|----------------|---------|")
    for num in sorted(LAYERS):
        label, purpose = LAYERS[num]
        members = sorted(m for m, lay in MODULE_LAYER.items() if lay == num and m in known)
        add(f"| {num} | **{label}** | {purpose} | {', '.join(f'`{m}`' for m in members) or '—'} |")
    add("")

    unmapped = sorted(known - set(MODULE_LAYER))
    if unmapped:
        problems.append("modules not in the layer table: " + ", ".join(unmapped))
    add("## Import graph")
    add("")
    add("```mermaid")
    add("flowchart TD")
    for name in sorted(graph):
        lay = MODULE_LAYER.get(name, 0)
        add(f'    {name.replace(".", "_")}["{name} <small>L{lay}</small>"]')
    for name in sorted(graph):
        for dep in sorted(graph[name]):
            add(f"    {name.replace('.', '_')} --> {dep.replace('.', '_')}")
    add("```")
    add("")
    add("### Edge notes")
    add("")
    add("| From | To | Note |")
    add("|------|----|------|")
    for name in sorted(graph):
        for dep in sorted(graph[name]):
            note = EDGE_NOTES.get((name, dep), "UNEXPLAINED — add a note in EDGE_NOTES")
            add(f"| `{name}` | `{dep}` | {note} |")
    add("")

    add("## Layer direction check")
    add("")
    violations: list[str] = []
    for name in sorted(graph):
        src = MODULE_LAYER.get(name)
        if src is None:
            continue
        for dep in sorted(graph[name]):
            dst = MODULE_LAYER.get(dep)
            if dst is None:
                continue
            if dst > src:
                violations.append(f"`{name}` (L{src}) imports `{dep}` (L{dst}) — upward edge")
    if violations:
        problems.extend(violations)
        add("| Violation |")
        add("|-----------|")
        for v in violations:
            add(f"| {v} |")
    else:
        add("All edges point downward or sideways. ✅")
    add("")

    add("## Cycles")
    add("")
    found = cycles(graph)
    if found:
        for scc in found:
            problems.append("import cycle: " + " <-> ".join(scc))
            add(f"- ❌ cycle: {' <-> '.join(f'`{m}`' for m in scc)}")
    else:
        add("No import cycles. ✅")
    add("")

    add("## Size")
    add("")
    add("| Module | Lines |")
    add("|--------|-------|")
    for name in sorted(modules):
        loc = sum(1 for _ in modules[name].read_text(encoding="utf-8").splitlines())
        add(f"| `{name}` | {loc} |")
    add("")

    return "\n".join(lines) + "\n", problems


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="fail if the committed map is stale")
    args = parser.parse_args()

    rendered, problems = build()

    if args.check:
        current = OUTPUT.read_text(encoding="utf-8") if OUTPUT.exists() else ""
        stale = current != rendered
        if stale:
            print(f"STALE: {OUTPUT.relative_to(ROOT)} does not match the tree")
            print("       run: python scripts/gen-architecture.py")
        if problems:
            print(f"STRUCTURE: {len(problems)} problem(s)")
            for problem in problems:
                print(f"  - {problem}")
        if stale or problems:
            return 1
        print(f"OK: {OUTPUT.relative_to(ROOT)} matches the tree")
        return 0

    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(rendered, encoding="utf-8")
    print(f"wrote {OUTPUT.relative_to(ROOT)}")
    for problem in problems:
        print(f"  - {problem}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
