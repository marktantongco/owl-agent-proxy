# OWL Agent Proxy — Agent Configuration

This file configures agent skills for the OWL Agent Proxy project (v7.1).

## Project

- **Name**: owl-agent-proxy
- **Description**: Multi-protocol HTTP defense system with caching, deduplication, domain rate limiting, tier-based proxy rotation, upstream harvesting, honeypot detection, sticky sessions, and MCP server for AI agents.
- **Entry point**: `proxy_defense.py`
- **Test command**: `python -m pytest tests/ -q`
- **Verify command**: `python scripts/verify-install.py --owl-home <path> --no-live`
- **CLI**: `./run.sh stats | fetch | harvest | mcp-selftest | verify`

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
- Skills pipeline framework: `docs/skills-framework/10-PIPELINES.md` (10 use cases)
- Research investigation skill: `~/.agents/skills/research-investigation-pipeline/SKILL.md`

## Conventions

- Language: English
- Testing: pytest with `tests/conftest.py` (hermetic, blocks outbound sockets)
- CI/CD: `.github/scripts/ci-check.sh` (protocol escalation + credential guard)
- Precedence for config: explicit argument → `config.json` → built-in default
