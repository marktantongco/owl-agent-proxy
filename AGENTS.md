# OWL Agent Proxy — Agent Configuration

This file configures agent skills for the OWL Agent Proxy project.

## Project

- **Name**: owl-agent-proxy
- **Description**: Client-side HTTP defense library + stdio MCP server + CLI with optional reverse proxy ingress. Provides proxy pooling, caching, deduplication, domain rate limiting, tier-based proxy rotation, upstream harvesting, honeypot detection, sticky sessions, and MCP server for AI agents. Core is NOT a reverse proxy — `reverse_proxy.py` adds optional HTTP ingress on a configurable port, forwarding through ResilientClient egress to upstream targets.
- **Entry point**: `proxy_defense.py` (client library) + `mcp_proxy_server.py` (stdio MCP server) + `run.sh` (CLI) + `reverse_proxy.py` (optional HTTP ingress)
- **Test command**: `python -m pytest tests/ -q`
- **Verify command**: `python scripts/verify-install.py --owl-home <path> --no-live`
- **CLI**: `./run.sh stats | fetch | harvest | mcp-selftest | serve | verify`

**Architecture alignment:**
- Core: client-side library + stdio MCP server + CLI (NOT a reverse proxy by itself)
- `reverse_proxy.py`: optional HTTP ingress layer that wraps ResilientClient egress as a reverse proxy
- Protocol escalation: http/1.1 → http/2 → ja3 → websocket → browser → stealth
- Circuit breaker: per-protocol failure tracking with cooldown
- Load balancing: multiple upstream targets with health-aware round-robin
- Trust the tests (507 passing), not docs prose (version drift: About v3.0 vs README v7.1)

## Skills

The following skills are installed and available in this project:

| Skill | Purpose |
|-------|---------|
| `grill-with-tail` | Technical design interviews with docs + Ponytail recommendations |
| `grill-powers` | Product PRD approval → autonomous technical delivery |
| `grill-with-docs` | Stateful grilling interview (writes GLOSSARY.md + ADRs) |
| `grilling` | Decision-by-decision clarification interview primitive |
| `domain-modeling` | Product concept, boundary, and invariant modeling |
| `to-spec` | PRD synthesis and publishing |
| `ponytail` | Recommendations during design interviews |
| `writing-plans` | Detailed implementation plans from approved designs |
| `subagent-driven-development` | Task dispatch with two-stage review |
| `executing-plans` | Inline plan execution with checkpoints |
| `systematic-debugging` | Root-cause debugging process |
| `verification-before-completion` | Evidence-based completion verification |
| `finishing-a-development-branch` | Merge/PR decision workflow |
| `triage` | Grill vague reports into workable items |
| `diagnosing-bugs` | Bug diagnosis workflow |
| `agent-run` (grill-engineering) | Automated ticket delivery: implement → verify → repair → merge |

## Conceptual Skills (14 total, installed as stubs in `skills/`)

| Skill | Stage | Source | Purpose |
|-------|-------|--------|---------|
| `agent-skills` | DEFINE | `skills/agent-skills/` | Discover/install/manage skills from skills.sh ecosystem |
| `codemap` | DEFINE | `skills/codemap/` | Map codebase structure — modules, dependencies, entry points, boundaries |
| `meta-skill` | DEFINE | `skills/meta-skill/` | Discover and install skills when capability is missing |
| `agent-reach` | DEFINE | `skills/agent-reach/` | Read/search across web platforms (Twitter, Reddit, YouTube, GitHub) |
| `duckduckgo-search` | DEFINE | `skills/duckduckgo-search/` | Free web search via DuckDuckGo — no API key |
| `exa-web-search-free` | DEFINE | `skills/exa-web-search-free/` | Free AI neural search via Exa MCP — no API key |
| `ralph-prompt-multi-task` | PLAN | `skills/ralph-prompt-multi-task/` | Generate phased prompts with sequential milestones |
| `orchestrate` | PLAN | `skills/orchestrate/` | Meta-orchestrate multi-agent workflow across all pipeline stages |
| `chain-of-thought` | PLAN | `skills/chain-of-thought/` | Step-by-step reasoning for architecture decisions |
| `headroom` | PLAN | `skills/headroom/` | Assess capacity, constraints, resource availability before build |
| `Caveman` | PLAN | `skills/Caveman/` | Simplest solution first — prevent over-engineering during design |
| `parallel-agent-skills` | BUILD | `skills/parallel-agent-skills/` | Execute multiple agent skills in parallel during implementation |
| `devils-advocate` | REVIEW | `skills/devils-advocate/` | Challenge assumptions, identify failure modes, stress-test before commit |
| `impeccable` | REVIEW | `skills/impeccable/` | Quality framework: audit, critique, distill, adapt, optimize, delight, result |

## 10 End-to-End Use-Case Pipelines

Each pipeline flows: **DEFINE → PLAN → BUILD → VERIFY → REVIEW → SHIP**

| # | Pipeline | Trigger | Key Skills |
|---|----------|---------|------------|
| 1 | Bug Fix | Something is broken | triage → diagnosing-bugs → systematic-debugging → writing-plans → executing-plans → verification-before-completion → finishing-a-development-branch |
| 2 | Feature Development | You want something new | grill-me → grilling → domain-modeling → to-spec → grill-powers → writing-plans → executing-plans → verification-before-completion → finishing-a-development-branch |
| 3 | Security Fix | Something isn't safe | triage → diagnosing-bugs → systematic-debugging → writing-plans → executing-plans → verification-before-completion → finishing-a-development-branch |
| 4 | Performance Optimization | It's too slow | triage → diagnosing-bugs → systematic-debugging → writing-plans → executing-plans → verification-before-completion → finishing-a-development-branch |
| 5 | Documentation & Spec | People need to understand it | grill-with-docs → domain-modeling → to-spec → ponytail → writing-plans → executing-plans → verification-before-completion → finishing-a-development-branch |
| 6 | Incident Response | Something big broke | triage → diagnosing-bugs → systematic-debugging → writing-plans → executing-plans → verification-before-completion → finishing-a-development-branch |
| 7 | Refactoring | It's messy | grill-me → grilling → to-spec → writing-plans → executing-plans → verification-before-completion → finishing-a-development-branch |
| 8 | Dependency Update | Tools are old | agent-browser → find-skills → writing-plans → executing-plans → verification-before-completion → finishing-a-development-branch |
| 9 | Architecture Review | You're changing the design | grill-me → grilling → domain-modeling → to-spec → grill-powers → writing-plans → executing-plans → verification-before-completion → finishing-a-development-branch |
| 10 | Full Product Delivery | You're making something from scratch | grill-powers → writing-plans → executing-plans → subagent-driven-development → systematic-debugging → verification-before-completion → finishing-a-development-branch → agent-run |

## Documentation Locations

- Issue tracker: `docs/agents/issue-tracker.md`
- Domain model: `docs/agents/domain.md`
- Architecture docs: `docs/V7_UPSTREAM.md`, `docs/PROTOCOL_ESCALATION_GUIDE.md`, `docs/LAYERED_FALLBACK.md`
- MCP integration: `docs/MCP_INTEGRATION.md`, `docs/STEALTH_BROWSER.md`
- Delivery automation: `docs/agents/grill-engineering/INTEGRATION.md`
- Skills pipeline framework: `docs/skills-framework/README.md` (full framework), `docs/skills-framework/10-PIPELINES.md` (10 use cases), `docs/skills-framework/QUICK_REFERENCE.md` (quick lookup)
- Conceptual skill stubs: `skills/` (14 skill SKILL.md files)
- Research investigation skill: `~/.agents/skills/research-investigation-pipeline/SKILL.md`
- Reverse proxy: `reverse_proxy.py` (v2 with protocol escalation, circuit breaker, load balancing)

## Conventions

- Language: English
- Testing: pytest with `tests/conftest.py` (hermetic, blocks outbound sockets) — 507 tests passing (trust tests over docs prose)
- CI/CD: `.github/scripts/ci-check.sh` (protocol escalation + credential guard)
- Precedence for config: explicit argument → `config.json` → built-in default
