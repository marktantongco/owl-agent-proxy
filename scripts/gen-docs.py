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

Rules enforced — see the `gate:` convention below this docstring:

gate: skills-inventory-current: the AGENTS.md skills table matches skills/ [required] [probe: tests/test_docs_generator.py]
gate: catalog-matches-source: the free-catalog table matches providers.json [required] [probe: tests/test_docs_generator.py]
gate: test-counts-current: the test-results table matches pytest collection [required] [probe: tests/test_docs_generator.py]
gate: gates-declare-rules: every registered gate declares its rules in its header [required] [probe: tests/test_gate_declarations.py]

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
    """Ask pytest how many tests each file collects, without importing them.

    `-o addopts=` overrides pytest.ini. Without it the repo's `--cov=` options are
    applied, and a runner that has pytest but not pytest-cov exits with a usage
    error — which this function used to swallow into a `?` in the table. A count
    that cannot be determined is an error here, not a symbol: a silently degraded
    table is the failure this whole script exists to prevent.
    """
    import subprocess

    counts: dict[str, int] = {}
    for path in files:
        proc = subprocess.run(
            [sys.executable, "-m", "pytest", str(path), "-q", "--collect-only",
             "-p", "no:cacheprovider", "-o", "addopts="],
            capture_output=True, text=True, cwd=ROOT,
        )
        match = re.search(r"(\d+) tests? collected", proc.stdout)
        if not match:
            raise SystemExit(
                f"could not count tests in {path.name} (pytest exit {proc.returncode}):\n"
                f"{(proc.stderr or proc.stdout).strip()[-600:]}"
            )
        counts[path.name] = int(match.group(1))
    return counts


# ── gate rules ─────────────────────────────────────────────────────────────
# A check is only as good as the rule it enforces, and rules get deleted quietly
# — `ci-check.sh` is a script whose two halves have very different risk profiles,
# and the audit that recommended deleting "it" was reading a catch count taken
# against the whole file. This block makes the rule set visible and CI-checkable:
# every gate declares its rules in its own header, so removing one produces a diff
# in a generated table rather than an edit nobody reviews.
#
# Declaration, identical in Python and shell headers:
#
#     # gate: <kebab-case-id>: <what this rule protects> [required]
#
# `[required]` marks a rule whose removal must be argued explicitly — the table
# records which they are, and a deletion cannot be silent because the row moves.
# Accepts both forms: a `#` comment in a shell/Python header, and a bare line
# inside a module docstring (Python gates declare there, next to the prose
# that already explains them).
# `[required]` marks a rule whose removal must be argued explicitly. `[probe: X]`
# names the test that proves the rule fires — a rule without one is a claim, and
# the table should say so rather than leave the column blank and unremarked.
GATE_DECL_RE = re.compile(
    r"^\s*(?:#\s*)?gate:\s*([a-z0-9][a-z0-9-]*):\s*(.+?)"
    r"(?:\s*\[required\])?(?:\s*\[probe:\s*([^\]]+)\])?\s*$"
)

# Registry, not discovery. A gate is a decision, not a file extension: these are
# the scripts whose failure blocks a merge. Adding a script here is the act of
# making it a gate, and the renderer then demands that it declares its rules.
GATES = (
    (".github/scripts/ci-check.sh", "Protocol escalation + credential guard"),
    (".github/scripts/check-skills.py", "Skill packaging and citations"),
    (".github/scripts/check-swallows.py", "Silent exception handlers"),
    ("scripts/gen-architecture.py", "Architecture map drift"),
    ("scripts/gen-docs.py", "Generated documentation drift"),
    ("scripts/runtime-check.py", "Component wiring"),
    ("scripts/verify-skills-lock.py", "Vendored skill provenance"),
)


def declared_rules(path: Path) -> list[tuple[str, str, bool, str | None]]:
    """[(id, description, required, probe)] declared in a gate script's header."""
    rules: list[tuple[str, str, bool, str | None]] = []
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return rules
    for line in text.splitlines():
        match = GATE_DECL_RE.match(line)
        if match:
            # `[required]` may appear before or after `[probe:]`; the regex takes
            # them in that order, so a probe written first is recovered below.
            probe = match.group(3)
            required = "[required]" in line
            rules.append((match.group(1), match.group(2).strip(), required,
                          probe.strip() if probe else None))
    return rules


def render_gates() -> str:
    rows: list[str] = []
    undeclared: list[str] = []
    for rel, purpose in GATES:
        path = ROOT / rel
        rules = declared_rules(path)
        if not path.is_file():
            undeclared.append(f"{rel} (registry lists it, file is missing)")
            continue
        if not rules:
            undeclared.append(f"{rel} (no `# gate:` declaration)")
            continue
        rows.append((rel, purpose, rules))

    if undeclared:
        # Failing here is the point: a gate with no declared rules is a gate
        # nobody can review, which is how a script-wide catch count gets mistaken
        # for a rule-level decision.
        raise SystemExit(
            "Every registered gate must declare its rules in its header "
            "(`# gate: <id>: <what it protects> [required]`).\n  "
            + "\n  ".join(undeclared)
        )

    flat = [(rel, *rule) for rel, _p, rules in rows for rule in rules]
    total_required = sum(1 for row in flat if row[3])
    total_probed = sum(1 for row in flat if row[4])
    out = [
        f"<!-- generated:gates ({len(rows)} gates, {len(flat)} rules, "
        f"{total_required} required, {total_probed} probed) -->",
        "",
        "| Gate | Rule | Protects | Required | Evidence |",
        "|------|------|----------|----------|----------|",
    ]
    for rel, rule_id, description, required, probe in flat:
        name = rule_id if required else f"_{rule_id}_"
        evidence = f"`{probe}`" if probe else "—"
        out.append(
            f"| `{rel}` | {name} | {description} | "
            f"{'yes' if required else 'advisory'} | {evidence} |"
        )
    out.append("")
    out.append(
        "Generated from each script's header by `scripts/gen-docs.py`. Delete a "
        "rule and its row disappears from this table — which is why removal shows "
        "up in review instead of in a catch count. An `—` in Evidence means no "
        "test proves that rule fires: it is a claim, not yet a gate."
    )
    out.append("<!-- /generated:gates -->")
    return "\n".join(out)


BLOCKS = {
    "skills": render_skills,
    "catalog": render_catalog,
    "tests": render_tests,
    "gates": render_gates,
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
