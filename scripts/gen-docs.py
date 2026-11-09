#!/usr/bin/env python3
"""Generate the hand-maintained tables in AGENTS.md from their real sources.

AGENTS.md is the 1,800-line operator document. Four of its tables describe the
repository's own contents, and every one of them had drifted:

* the skills inventory listed a capitalised `Caveman` and a `github-researcher`
  that does not exist, while omitting the eight reasoning skills and the six
  vendored research skills;
* the free-catalog table claimed model counts and rate limits that disagree
  with `gateway/free_catalog/providers.json` (Cloudflare "7 named + 55 more"
  vs 8 in the file, ModelScope "2 named + more" vs 3);
* the test-results table was written by hand.

Those three are now generated between markers and verified in CI:

    python scripts/gen-docs.py            # rewrite the managed blocks
    python scripts/gen-docs.py --check    # exit 1 when AGENTS.md is stale

Only text between `<!-- generated:<name> -->` and `<!-- /generated:<name> -->`
is touched. Anything outside is human-owned and never rewritten.

Stdlib only.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
AGENTS = ROOT / "AGENTS.md"
SKILLS = ROOT / "skills"
CATALOG = ROOT / "gateway" / "free_catalog" / "providers.json"

# Stage comes from the SKILL.md frontmatter when present; this map covers the
# published skills that do not declare one.
DEFAULT_STAGE = {
    "agent-reach": "DEFINE", "agent-skills": "DEFINE", "codemap": "DEFINE",
    "duckduckgo-search": "DEFINE", "exa-web-search-free": "DEFINE",
    "meta-skill": "DEFINE", "github-research": "DEFINE",
    "parallel-deep-research": "DEFINE", "parallel-findall": "DEFINE",
    "you-web": "DEFINE", "free-search-aggregator": "DEFINE",
    "freeunlimited-websearch": "DEFINE", "owl-proxy": "SHIP",
    "owl-proxy-mcp": "SHIP", "impeccable": "REVIEW",
    "devils-advocate": "REVIEW", "headroom": "PLAN",
    "orchestrate": "PLAN", "chain-of-thought": "PLAN",
    "ralph-prompt-multi-task": "PLAN", "parallel-agent-skills": "BUILD",
    "caveman": "PLAN",
}


def frontmatter(skill_md: Path) -> dict[str, str]:
    text = skill_md.read_text(encoding="utf-8")
    if not text.startswith("---"):
        return {}
    body = text.split("---", 2)[1]
    meta: dict[str, str] = {}
    for line in body.splitlines():
        key, sep, value = line.partition(":")
        if sep:
            meta[key.strip()] = value.strip().strip("\"'")
    return meta


def skill_rows() -> list[tuple[str, str, str]]:
    """(name, stage, source) for every discoverable skill, sorted by name."""
    rows = []
    for skill_md in sorted(SKILLS.glob("*/SKILL.md")):
        name = skill_md.parent.name
        meta = frontmatter(skill_md)
        stage = meta.get("pipeline_stage") or DEFAULT_STAGE.get(name, "—")
        source = meta.get("source") or "not declared in SKILL.md"
        rows.append((name, stage, source))
    return rows


def render_skills() -> str:
    rows = skill_rows()
    out = [
        f"<!-- generated:skills ({len(rows)} skills in skills/, each skills/<name>/SKILL.md) -->",
        "| Skill | Stage | Source |",
        "|-------|-------|--------|",
    ]
    for name, stage, source in rows:
        out.append(f"| `{name}` | {stage} | {source} |")
    out.append("<!-- /generated:skills -->")
    return "\n".join(out)


def render_catalog() -> str:
    data = json.loads(CATALOG.read_text(encoding="utf-8"))
    providers = data["providers"]
    total_models = sum(len(p.get("models", [])) for p in providers)
    out = [
        f"<!-- generated:catalog ({len(providers)} providers, {total_models} models, "
        f"from gateway/free_catalog/providers.json) -->",
        f"*Source: `{data.get('source', 'providers.json')}`"
        + (f" — last updated {data['last_updated']}" if data.get("last_updated") else "")
        + "*",
        "",
        "| Provider | Category | Models | Example rate limit |",
        "|----------|----------|--------|--------------------|",
    ]
    for provider in sorted(providers, key=lambda p: (p.get("category", ""), p.get("name", ""))):
        models = provider.get("models", [])
        # Use the provider's own most-informative rate limit rather than inventing
        # a summary: first model that is not "-".
        rate = next((m.get("rate_limit") for m in models if m.get("rate_limit") not in (None, "-", "")), "—")
        out.append(
            f"| {provider['name']} | {provider.get('category', '—')} | {len(models)} | {rate} |"
        )
    out.append("<!-- /generated:catalog -->")
    return "\n".join(out)


def render_tests() -> str:
    """One row per test file, with the count pytest collects for that file."""
    files = sorted(p for p in (ROOT / "tests").glob("test_*.py"))
    out = [
        "<!-- generated:tests (counts from pytest --collect-only; run `python scripts/gen-docs.py`) -->",
        "| Test file | Tests | Covers |",
        "|-----------|-------|--------|",
    ]
    covers = {
        "test_proxy_defense.py": "cache, dedupe, rate limit, rotation, filter pipeline, middleware, protocols",
        "test_mcp_server.py": "JSON-RPC framing, all tools, stdout purity, real stdio subprocess",
        "test_proxy_harvester.py": "source schemas, source health, affinity, honeypot hashing, probes",
        "test_memory_backend.py": "SQLite memory backend, FTS, cross-process lock",
        "test_reverse_proxy.py": "ingress, circuit breaker, load balancing, stealth mode",
        "test_v71_integration.py": "sticky selection, quarantine, trimming, persistence, config merge",
        "test_free_catalog.py": "catalog loading, routes, paid-vendor filter",
        "test_stealth.py": "stealth rung gating and fingerprint profiles",
        "test_gateway.py": "auth, circuit breaker, cache, billing, router",
        "test_pool_backend.py": "pool persistence backend",
        "test_architecture_check.py": "the drift detector itself (proves it detects)",
        "test_docs_generator.py": "the table generator (proves a stale table fails)",
    }
    counts = _collect_counts(files)
    total = 0
    for path in files:
        n = counts.get(path.name, "?")
        total += n if isinstance(n, int) else 0
        out.append(f"| `tests/{path.name}` | {n} | {covers.get(path.name, '—')} |")
    out.append("")
    out.append(f"**Total: {total} tests**, all offline and hermetic.")
    out.append("<!-- /generated:tests -->")
    return "\n".join(out)


def _collect_counts(files: list[Path]) -> dict[str, int]:
    """Ask pytest how many tests each file collects, without importing them."""
    import subprocess

    counts: dict[str, int] = {}
    for path in files:
        proc = subprocess.run(
            [sys.executable, "-m", "pytest", str(path), "-q", "--collect-only", "-p", "no:cacheprovider"],
            capture_output=True, text=True, cwd=ROOT,
        )
        match = re.search(r"(\d+) tests? collected", proc.stdout)
        if match:
            counts[path.name] = int(match.group(1))
    return counts


BLOCKS = {
    "skills": render_skills,
    "catalog": render_catalog,
    "tests": render_tests,
}


def rewrite(text: str, name: str, rendered: str) -> str:
    start = f"<!-- generated:{name} "
    begin = text.find(start)
    if begin == -1:
        raise SystemExit(
            f"AGENTS.md has no '{start}...' marker. Add it where the {name} table belongs."
        )
    end_marker = f"<!-- /generated:{name} -->"
    end = text.find(end_marker, begin)
    if end == -1:
        raise SystemExit(f"AGENTS.md has no closing '{end_marker}'")
    # Normalise the seams so the marker, the block and the surrounding prose are
    # separated by exactly one blank line — a table glued to an HTML comment does
    # not render in CommonMark.
    lines = rendered.split("\n")
    head_line, body, close_line = lines[0], lines[1:-1], lines[-1]
    block = head_line + "\n\n" + "\n".join(body).strip("\n") + "\n\n" + close_line
    before = text[:begin].rstrip("\n")
    after = text[end + len(end_marker):].lstrip("\n")
    return before + "\n\n" + block + "\n\n" + after


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="fail when AGENTS.md is stale")
    args = parser.parse_args()

    original = AGENTS.read_text(encoding="utf-8")
    updated = original
    for name, render in BLOCKS.items():
        rendered = render()
        if not rendered:
            print(f"SKIP: {name} renderer returned nothing (not implemented)")
            continue
        updated = rewrite(updated, name, rendered)

    if args.check:
        if updated != original:
            print("STALE: AGENTS.md generated blocks do not match their sources")
            print("       run: python scripts/gen-docs.py")
            return 1
        print("OK: AGENTS.md generated blocks match their sources")
        return 0

    if updated == original:
        print("OK: AGENTS.md already current")
        return 0
    AGENTS.write_text(updated, encoding="utf-8")
    print("wrote AGENTS.md")
    return 0


if __name__ == "__main__":
    sys.exit(main())
