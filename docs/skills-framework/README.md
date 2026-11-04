# Skills Framework — OWL Agent Proxy

**Consolidated skills framework** covering 10 end-to-end use-case pipelines, skill handoff contracts, decision gates, and agent-run commands.

**Operating Instructions:** smp5.4pd.md (Tactical Merge) — Mode: 🐜 Systematic

---

## Overview

The skills framework maps every job type (bug fix, feature, security, performance, docs, incident, refactor, dependency, architecture, full delivery) through a 6-stage pipeline: **DEFINE → PLAN → BUILD → VERIFY → REVIEW → SHIP**.

26 skills are installed at `~/.agents/skills/` (16 original + 10 research/conceptual). 10 conceptual skill SKILL.md stubs are in `skills/`.

---

## 10 End-to-End Use-Case Pipelines

| # | Pipeline | Trigger | DEFINE | PLAN | BUILD | VERIFY | REVIEW | SHIP |
|---|----------|---------|--------|------|-------|--------|--------|------|
| 1 | Bug Fix | Something is broken | triage, diagnosing-bugs | systematic-debugging | writing-plans, executing-plans | verification-before-completion | finishing-a-development-branch | finishing-a-development-branch |
| 2 | Feature Development | You want something new | agent-skills, codemap, grill-me, grilling | domain-modeling, to-spec, grill-powers, ralph-prompt-multi-task, chain-of-thought, headroom, Caveman | writing-plans, executing-plans, parallel-agent-skills | verification-before-completion | devils-advocate, impeccable, finishing-a-development-branch | finishing-a-development-branch |
| 3 | Security Fix | Something isn't safe | triage, diagnosing-bugs | systematic-debugging | writing-plans, executing-plans | verification-before-completion | devils-advocate, impeccable, finishing-a-development-branch | finishing-a-development-branch |
| 4 | Performance Optimization | It's too slow | triage, diagnosing-bugs | systematic-debugging | writing-plans, executing-plans | verification-before-completion | devils-advocate, impeccable, finishing-a-development-branch | finishing-a-development-branch |
| 5 | Documentation & Spec | People need to understand it | agent-skills, codemap, grill-with-docs | domain-modeling, to-spec, ponytail, ralph-prompt-multi-task, Caveman | writing-plans, executing-plans, parallel-agent-skills | verification-before-completion | devils-advocate, impeccable, finishing-a-development-branch | finishing-a-development-branch |
| 6 | Incident Response | Something big broke | triage, diagnosing-bugs | systematic-debugging | writing-plans, executing-plans | verification-before-completion | devils-advocate, impeccable, finishing-a-development-branch | finishing-a-development-branch |
| 7 | Refactoring | It's messy | agent-skills, codemap, grill-me, grilling | to-spec, chain-of-thought, headroom, Caveman | writing-plans, executing-plans, parallel-agent-skills | verification-before-completion | devils-advocate, impeccable, finishing-a-development-branch | finishing-a-development-branch |
| 8 | Dependency Update | Tools are old | agent-skills, codemap, agent-browser, find-skills | headroom | writing-plans, executing-plans, parallel-agent-skills | verification-before-completion | devils-advocate, impeccable, finishing-a-development-branch | finishing-a-development-branch |
| 9 | Architecture Review | You're changing the design | agent-skills, codemap, grill-me, grilling | domain-modeling, to-spec, grill-powers, ralph-prompt-multi-task, chain-of-thought, headroom, Caveman | writing-plans, executing-plans, parallel-agent-skills | verification-before-completion | devils-advocate, impeccable, finishing-a-development-branch | finishing-a-development-branch |
| 10 | Full Product Delivery | You're making something from scratch | agent-skills, codemap, grill-powers | ralph-prompt-multi-task, orchestrate, chain-of-thought, headroom, Caveman | writing-plans, executing-plans, subagent-driven-development, parallel-agent-skills, systematic-debugging | verification-before-completion | devils-advocate, impeccable, finishing-a-development-branch | agent-run, finishing-a-development-branch |

---

## Conceptual Skill Stage Alignment

| # | Conceptual Skill | Pipeline Stage | Role |
|---|-----------------|----------------|------|
| 1 | `agent-skills` | DEFINE | Discover, install, manage skills from skills.sh ecosystem |
| 2 | `codemap` | DEFINE | Map codebase structure — modules, dependencies, entry points, boundaries |
| 3 | `ralph-prompt-multi-task` | PLAN | Generate phased prompts with sequential milestones for multi-task breakdown |
| 4 | `orchestrate` | PLAN | Meta-orchestrate multi-agent workflow across all pipeline stages |
| 5 | `chain-of-thought` | PLAN | Step-by-step reasoning for architecture decisions and trade-off analysis |
| 6 | `headroom` | PLAN | Assess capacity, constraints, resource availability before committing to build |
| 7 | `Caveman` | PLAN | Simplest solution first — prevent over-engineering during design |
| 8 | `parallel-agent-skills` | BUILD | Execute multiple agent skills in parallel during implementation |
| 9 | `devils-advocate` | REVIEW | Systematically challenge assumptions, identify failure modes, stress-test before commit |
| 10 | `impeccable` | REVIEW | Full-spectrum quality framework: audit, critique, distill, adapt, optimize, delight, result |

---

## Skill Handoff Contracts

| Phase | Input | Output | Handoff To |
|-------|-------|--------|------------|
| DEFINE | Problem statement, job type | Clarified scope, research results, codebase map, skills inventory | PLAN |
| PLAN | Clarified scope | PRD, task list, GLOSSARY.md, ADRs, phased prompts, capacity assessment | BUILD |
| BUILD | PRD, tasks | Implemented code, tests, parallel execution results | VERIFY |
| VERIFY | Implemented code | Test results, evidence | REVIEW |
| REVIEW | Code, tests | Challenge log, quality report, approval decision | SHIP |
| SHIP | Approved code | Merged branch, deployed release | Complete |

---

## Decision Gates

| Gate | From → To | Condition |
|------|-----------|-----------|
| G1 | DEFINE → PLAN | Requirements clarified, scope agreed |
| G2 | PLAN → BUILD | PRD approved, tasks broken down, headroom confirmed |
| G3 | BUILD → VERIFY | Implementation complete, tests written |
| G4 | VERIFY → REVIEW | All tests pass, evidence captured |
| G5 | REVIEW → SHIP | Code reviewed, devils-advocate challenged, impeccable quality gate passed |
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
| parallel-deep-research | parallel-web/parallel-agent-skills | DEFINE |
| parallel-findall | parallel-web/parallel-agent-skills | DEFINE |
| github-research | lingzhi227/agent-research-skills | DEFINE |
| free-search-aggregator | vulcanusalex/free-search-aggregator | DEFINE |
| freeUnlimited-websearch | lngu/openclaw-skill-freeunlimited-websearch | DEFINE |
| you-web | youdotcom-oss/agent-skills | DEFINE |
| agent-skills | Custom stub (`skills/agent-skills/`) | DEFINE |
| codemap | Custom stub (`skills/codemap/`) | DEFINE |
| ralph-prompt-multi-task | Custom stub (`skills/ralph-prompt-multi-task/`) | PLAN |
| orchestrate | Custom stub (`skills/orchestrate/`) | PLAN |
| chain-of-thought | Custom stub (`skills/chain-of-thought/`) | PLAN |
| headroom | Custom stub (`skills/headroom/`) | PLAN |
| Caveman | Custom stub (`skills/Caveman/`) | PLAN |
| parallel-agent-skills | Custom stub (`skills/parallel-agent-skills/`) | BUILD |
| devils-advocate | Custom stub (`skills/devils-advocate/`) | REVIEW |
| impeccable | Custom stub (`skills/impeccable/`) | REVIEW |

---

## Skill Gaps (still not published anywhere)

| Skill | Status |
|-------|--------|
| `meta-skill` | Not found in vercel-labs/skills, mattpocock/skills, or parallel-web/parallel-agent-skills |
| `code-review` | mattpocock/skills engineering — available but not yet installed |
| `brainstorming` | obra/superpowers — available but not yet installed |
| `agent-reach` | Not found in any major skill repository |
| `duckduckgo-search` | Not found as a published skill |
| `exa-web-search-free` | Not found as a published skill |

---

## Research Investigation Skill

**Path:** `~/.agents/skills/research-investigation-pipeline/SKILL.md`

**Stack:** `parallel-deep-research`, `parallel-findall`, `github-research`, `free-search-aggregator`, `freeUnlimited-websearch`, `you-web`, `agent-reach`, `meta-skill` (missing), `brainstorming`, `grilling`, `grill-me`, `writing-plans`, `to-spec`, `domain-modeling`, `grill-with-docs`

**Install:**
```bash
npx skills add parallel-web/parallel-agent-skills --skill parallel-deep-research --skill parallel-findall --agent '*' -y
npx skills add lingzhi227/agent-research-skills --skill github-research --agent '*' -y
npx skills add https://github.com/vulcanusalex/free-search-aggregator --skill free-search-aggregator --agent '*' -y
npx skills add https://github.com/lngu/openclaw-skill-freeunlimited-websearch --skill freeUnlimited-websearch --agent '*' -y
npx skills add https://github.com/youdotcom-oss/agent-skills --skill you-web --agent '*' -y
```

---

## File Locations

- Pipeline definition: `docs/skills-framework/10-PIPELINES.md`
- Framework overview: `docs/skills-framework/README.md` (this file)
- Quick reference: `docs/skills-framework/QUICK_REFERENCE.md`
- Skill stubs: `skills/` (10 conceptual skill SKILL.md files)
- Skill installation: `~/.agents/skills/` (26 skills installed)
- Delivery tool: `tools/grill-engineering/` + `agent-run` CLI
- Project config: `AGENTS.md`, `docs/agents/issue-tracker.md`, `docs/agents/domain.md`
