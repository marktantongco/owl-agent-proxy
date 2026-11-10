# Skills Framework — Quick Reference

**At-a-glance reference** for the 10 end-to-end use-case pipelines, common commands, and skill lookup.

**Operating Instructions:** smp5.4pd.md — Mode: 🚀 Speed

---

## Project Alignment

**OWL Agent Proxy core is NOT a reverse proxy.** It is a client-side HTTP defense library + stdio MCP server + CLI. `reverse_proxy.py` adds optional HTTP ingress — `./run.sh serve` wraps ResilientClient egress as a reverse proxy with protocol escalation, circuit breaker, and load balancing.

**Version drift:** Docs disagree (About says v3.0, README says v7.1). Trust tests (598 passing) and the generated `docs/architecture/MODULE_GRAPH.md`, not prose.

---

## 10 Pipelines at a Glance

| # | Pipeline | Trigger | Flow (abbreviated) |
|---|----------|---------|-------------------|
| 1 | Bug Fix | Something is broken | triage → diagnose → debug → plan → implement → verify → release |
| 2 | Feature Development | You want something new | discover → map → clarify → spec → approve → plan → reason → capacity → simple → implement → parallel → verify → challenge → quality → release |
| 3 | Security Fix | Something isn't safe | triage → diagnose → debug → plan → implement → verify → challenge → quality → release |
| 4 | Performance Optimization | It's too slow | triage → diagnose → debug → plan → implement → verify → challenge → quality → release |
| 5 | Documentation & Spec | People need to understand it | discover → map → document → model → spec → recommend → plan → simple → implement → parallel → verify → challenge → quality → release |
| 6 | Incident Response | Something big broke | triage → diagnose → debug → plan → implement → verify → challenge → quality → release |
| 7 | Refactoring | It's messy | discover → map → clarify → spec → reason → capacity → simple → implement → parallel → verify → challenge → quality → release |
| 8 | Dependency Update | Tools are old | discover → map → browse → find → capacity → plan → implement → parallel → verify → challenge → quality → release |
| 9 | Architecture Review | You're changing the design | discover → map → clarify → spec → approve → plan → reason → capacity → simple → implement → parallel → verify → challenge → quality → release |
| 10 | Full Product Delivery | You're making something from scratch | discover → map → approve → plan → orchestrate → reason → capacity → simple → implement → parallel → debug → verify → challenge → quality → release → automate |

---

## Stage → Skill Lookup

| Stage | Skills |
|-------|--------|
| DEFINE | triage, diagnosing-bugs, grill-me, grilling, find-skills, agent-browser, grill-with-docs, parallel-deep-research, parallel-findall, github-research, free-search-aggregator, freeUnlimited-websearch, you-web, agent-skills, codemap, meta-skill, agent-reach, duckduckgo-search, exa-web-search-free |
| PLAN | domain-modeling, to-spec, grill-powers, grill-with-tail, ponytail, ralph-prompt-multi-task, orchestrate, chain-of-thought, headroom, caveman |
| BUILD | writing-plans, executing-plans, subagent-driven-development, systematic-debugging, parallel-agent-skills |
| VERIFY | verification-before-completion, systematic-debugging |
| REVIEW | code-review, finishing-a-development-branch, devils-advocate, impeccable |
| SHIP | agent-run, finishing-a-development-branch |

---

## Conceptual Skills — 10 Stubs in `skills/`

| # | Skill | Stage | One-line purpose |
|---|-------|-------|------------------|
| 1 | agent-skills | DEFINE | Discover/install/manage skills from skills.sh ecosystem |
| 2 | codemap | DEFINE | Map codebase structure — modules, dependencies, entry points, boundaries |
| 3 | meta-skill | DEFINE | Discover and install skills when capability is missing |
| 4 | agent-reach | DEFINE | Read/search across web platforms (Twitter, Reddit, YouTube, GitHub) |
| 5 | duckduckgo-search | DEFINE | Free web search via DuckDuckGo — no API key |
| 6 | exa-web-search-free | DEFINE | Free AI neural search via Exa MCP — no API key |
| 7 | ralph-prompt-multi-task | PLAN | Generate phased prompts with sequential milestones |
| 8 | orchestrate | PLAN | Meta-orchestrate multi-agent workflow across all pipeline stages |
| 9 | chain-of-thought | PLAN | Step-by-step reasoning for architecture decisions |
| 10 | headroom | PLAN | Assess capacity, constraints, resource availability before build |
| 11 | caveman | PLAN | Simplest solution first — prevent over-engineering during design |
| 12 | parallel-agent-skills | BUILD | Execute multiple agent skills in parallel during implementation |
| 13 | devils-advocate | REVIEW | Challenge assumptions, identify failure modes, stress-test before commit |
| 14 | impeccable | REVIEW | Quality framework: audit, critique, distill, adapt, optimize, delight, result |

---

## Research Stack (install before use)

```bash
npx skills add parallel-web/parallel-agent-skills --skill parallel-deep-research --skill parallel-findall --agent '*' -y
npx skills add lingzhi227/agent-research-skills --skill github-research --agent '*' -y
npx skills add https://github.com/vulcanusalex/free-search-aggregator --skill free-search-aggregator --agent '*' -y
npx skills add https://github.com/lngu/openclaw-skill-freeunlimited-websearch --skill freeUnlimited-websearch --agent '*' -y
npx skills add https://github.com/youdotcom-oss/agent-skills --skill you-web --agent '*' -y
```

---

## agent-run Commands

```bash
agent-run doctor                          # Check environment readiness
agent-run run <issue> --repo <owner/repo> # Automated ticket delivery
```

---

## Decision Gates (6)

| Gate | From → To | Condition |
|------|-----------|-----------|
| G1 | DEFINE → PLAN | Scope clarified |
| G2 | PLAN → BUILD | PRD approved, headroom confirmed |
| G3 | BUILD → VERIFY | Code + tests done |
| G4 | VERIFY → REVIEW | Tests pass |
| G5 | REVIEW → SHIP | Review approved, devils-advocate cleared, impeccable gate passed |
| G6 | SHIP → Complete | Merged / closed |

---

## Verification

```bash
python -m pytest tests/ -q                                    # Test suite (598 passed, 82% coverage)
python scripts/verify-install.py --owl-home <path> --no-live  # Install verify (18 PASS, 0 FAIL, 2 SKIP)
agent-run doctor                                              # Delivery tool readiness
```

---

## File Locations

- Full framework: `docs/skills-framework/README.md`
- Pipeline definition: `docs/skills-framework/10-PIPELINES.md`
- Conceptual skill stubs: `skills/` (10 SKILL.md files)
- Research skill: `~/.agents/skills/research-investigation-pipeline/SKILL.md`
- Project config: `AGENTS.md`
