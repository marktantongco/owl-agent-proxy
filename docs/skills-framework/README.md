# Skills Framework — OWL Agent Proxy

**Consolidated skills framework** covering 10 end-to-end use-case pipelines, skill handoff contracts, decision gates, and agent-run commands.

**Operating Instructions:** smp5.4pd.md (Tactical Merge) — Mode: 🐜 Systematic

---

## Overview

The skills framework maps every job type (bug fix, feature, security, performance, docs, incident, refactor, dependency, architecture, full delivery) through a 6-stage pipeline: **DEFINE → PLAN → BUILD → VERIFY → REVIEW → SHIP**.

16 skills are installed at `~/.agents/skills/`. A research investigation skill is available at `~/.agents/skills/research-investigation-pipeline/`.

---

## 10 End-to-End Use-Case Pipelines

| # | Pipeline | Trigger | DEFINE | PLAN | BUILD | VERIFY | REVIEW | SHIP |
|---|----------|---------|--------|------|-------|--------|--------|------|
| 1 | Bug Fix | Something is broken | triage, diagnosing-bugs | systematic-debugging | writing-plans, executing-plans | verification-before-completion | finishing-a-development-branch | finishing-a-development-branch |
| 2 | Feature Development | You want something new | grill-me, grilling | domain-modeling, to-spec, grill-powers | writing-plans, executing-plans | verification-before-completion | finishing-a-development-branch | finishing-a-development-branch |
| 3 | Security Fix | Something isn't safe | triage, diagnosing-bugs | systematic-debugging | writing-plans, executing-plans | verification-before-completion | finishing-a-development-branch | finishing-a-development-branch |
| 4 | Performance Optimization | It's too slow | triage, diagnosing-bugs | systematic-debugging | writing-plans, executing-plans | verification-before-completion | finishing-a-development-branch | finishing-a-development-branch |
| 5 | Documentation & Spec | People need to understand it | grill-with-docs | domain-modeling, to-spec, ponytail | writing-plans, executing-plans | verification-before-completion | finishing-a-development-branch | finishing-a-development-branch |
| 6 | Incident Response | Something big broke | triage, diagnosing-bugs | systematic-debugging | writing-plans, executing-plans | verification-before-completion | finishing-a-development-branch | finishing-a-development-branch |
| 7 | Refactoring | It's messy | grill-me, grilling | to-spec | writing-plans, executing-plans | verification-before-completion | finishing-a-development-branch | finishing-a-development-branch |
| 8 | Dependency Update | Tools are old | agent-browser, find-skills | — | writing-plans, executing-plans | verification-before-completion | finishing-a-development-branch | finishing-a-development-branch |
| 9 | Architecture Review | You're changing the design | grill-me, grilling | domain-modeling, to-spec, grill-powers | writing-plans, executing-plans | verification-before-completion | finishing-a-development-branch | finishing-a-development-branch |
| 10 | Full Product Delivery | You're making something from scratch | grill-powers | writing-plans | executing-plans, subagent-driven-development, systematic-debugging | verification-before-completion | finishing-a-development-branch | agent-run, finishing-a-development-branch |

---

## Skill Handoff Contracts

| Phase | Input | Output | Handoff To |
|-------|-------|--------|------------|
| DEFINE | Problem statement, job type | Clarified scope, research results | PLAN |
| PLAN | Clarified scope | PRD, task list, GLOSSARY.md, ADRs | BUILD |
| BUILD | PRD, tasks | Implemented code, tests | VERIFY |
| VERIFY | Implemented code | Test results, evidence | REVIEW |
| REVIEW | Code, tests | Review feedback, approval decision | SHIP |
| SHIP | Approved code | Merged branch, deployed release | Complete |

---

## Decision Gates

| Gate | From → To | Condition |
|------|-----------|-----------|
| G1 | DEFINE → PLAN | Requirements clarified, scope agreed |
| G2 | PLAN → BUILD | PRD approved, tasks broken down |
| G3 | BUILD → VERIFY | Implementation complete, tests written |
| G4 | VERIFY → REVIEW | All tests pass, evidence captured |
| G5 | REVIEW → SHIP | Code reviewed, approved for merge |
| G6 | SHIP → Complete | Branch merged or PR closed |

---

## agent-run Commands (grill-engineering)

```bash
# Check environment readiness
agent-run doctor

# Run automated ticket delivery (implement → verify → repair → merge)
agent-run run <issue-number> --repo marktantongco/owl-agent-proxy
```

**Requirements:** CPython 3.11+, Git 2.40+, gh, Codex CLI, bwrap, openssl, user systemd (Linux only).

---

## Installed Skills (~/.agents/skills/)

| Skill | Source | Pipeline Stage |
|-------|--------|---------------|
| triage | mattpocock/skills | DEFINE |
| diagnosing-bugs | mattpocock/skills | DEFINE |
| grill-with-docs | mattpocock/skills | PLAN |
| grilling | mattpocock/skills | PLAN |
| domain-modeling | mattpocock/skills | PLAN |
| to-spec | mattpocock/skills | PLAN |
| ponytail | DietrichGebert/ponytail | PLAN |
| grill-with-tail | andre-lmarinho/grillwith-tail | PLAN |
| grill-powers | okht/grill-powers | PLAN/SHIP |
| writing-plans | hazikkhatri/superpowers | BUILD |
| subagent-driven-development | hazikkhatri/superpowers | BUILD |
| executing-plans | hazikkhatri/superpowers | BUILD |
| systematic-debugging | hazikkhatri/superpowers | BUILD/VERIFY |
| verification-before-completion | hazikkhatri/superpowers | VERIFY |
| finishing-a-development-branch | hazikkhatri/superpowers | REVIEW/SHIP |
| agent-run | GRD-Chang/grill-engineering | SHIP |

---

## Skill Gaps (not published / not installed)

| Skill | Status |
|-------|--------|
| meta-skill | Not found in vercel-labs/skills or mattpocock/skills |
| parallel-findall | Not found in vercel-labs/skills or mattpocock/skills |
| code-review | mattpocock/skills engineering — not yet installed |
| brainstorming | obra/superpowers — not yet installed |
| ralph-prompt-multi-task | Not published |
| orchestrate | Not published |
| chain-of-thought | Not published |
| headroom | Not published |
| Caveman | Not published |
| devils-advocate | Not published |
| codemap | Not published |
| parallel-agent-skills | Not published |
| agent-skills | Not published |
| pbakaus/impeccable | Not published |

---

## Research Investigation Skill

**Path:** `~/.agents/skills/research-investigation-pipeline/SKILL.md`

**Stack:** `parallel-deep-research`, `duckduckgo-search`, `exa-web-search-free`, `free-search-aggregator`, `freeUnlimited-websearch`, `you-web`, `agent-reach`, `meta-skill` (custom), `parallel-findall` (custom), `brainstorming`, `grilling`, `grill-me`, `writing-plans`, `to-spec`, `domain-modeling`, `grill-with-docs`

**Install:**
```bash
npx skills add https://github.com/vulcanusalex/free-search-aggregator --skill free-search-aggregator --agent '*' -y
npx skills add https://github.com/lngu/openclaw-skill-freeunlimited-websearch --skill freeUnlimited-websearch --agent '*' -y
npx skills add https://github.com/youdotcom-oss/agent-skills --skill you-web --agent '*' -y
```

---

## File Locations

- Pipeline definition: `docs/skills-framework/10-PIPELINES.md`
- Framework overview: `docs/skills-framework/README.md` (this file)
- Quick reference: `docs/skills-framework/QUICK_REFERENCE.md`
- Skill installation: `~/.agents/skills/` (16 skills installed)
- Delivery tool: `tools/grill-engineering/` + `agent-run` CLI
- Project config: `AGENTS.md`, `docs/agents/issue-tracker.md`, `docs/agents/domain.md`
