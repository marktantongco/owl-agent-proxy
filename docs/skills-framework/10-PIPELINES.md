# 10 End-to-End Use-Case Pipelines

**Consolidated from stacks 1–5:** phase skills, 10 use-case pipelines, DEFINE/PLAN/BUILD/VERIFY/REVIEW/SHIP stage mapping, research investigation stack, 10 conceptual skills integrated.

**Operating Instructions:** smp5.4pd.md (Tactical Merge) — Mode: 🐜 Systematic

---

## Project Alignment

**OWL Agent Proxy is NOT a reverse proxy.** It is a client-side HTTP defense library + stdio MCP server + CLI. `run.sh` has no `serve` subcommand and cannot replace an `:8080` listener. Its strength is in proxy harvesting/validation, honeypot checks, sticky sessions, and 484 offline tests.

**Version drift note:** Docs disagree (About says v3.0, README says v7.1). Trust the tests (484 passing), not the prose.

---

## Consolidated Stage-to-Skill Mapping

| Pipeline Stage | Deployment Stage | Skills |
|----------------|------------------|--------|
| **DEFINE** | Stage 1 – Discover & Research | `find-skills`, `agent-browser`, `grill-me`, `grilling`, `parallel-deep-research`, `duckduckgo-search`, `exa-web-search-free`, `free-search-aggregator`, `freeUnlimited-websearch`, `you-web`, `agent-reach`, `github-research`, `codemap`, `agent-skills` *(meta-skill: NOT FOUND — gap documented)* |
| **PLAN** | Stage 2 – Plan & Architect | `domain-modeling`, `to-spec`, `grill-with-docs`, `grill-with-tail`, `grill-powers`, `ponytail`, `brainstorming`, `ralph-prompt-multi-task`, `orchestrate`, `chain-of-thought`, `headroom`, `Caveman` |
| **BUILD** | Stage 3 – Execute | `writing-plans`, `executing-plans`, `subagent-driven-development`, `systematic-debugging`, `parallel-agent-skills` |
| **VERIFY** | Stage 3 – Verify | `verification-before-completion`, `systematic-debugging` |
| **REVIEW** | Stage 3 – Review | `code-review`, `finishing-a-development-branch`, `devils-advocate`, `impeccable` |
| **SHIP** | Stage 3 – Ship | `agent-run` (grill-engineering CLI), `finishing-a-development-branch` |

---

## Conceptual Skill Stage Alignment

| # | Conceptual Skill | Pipeline Stage | Role in Pipeline |
|---|-----------------|----------------|------------------|
| 1 | `agent-skills` | DEFINE | Discover, install, and manage skills across skills.sh ecosystem before planning |
| 2 | `codemap` | DEFINE | Map codebase structure — modules, dependencies, entry points, boundaries — for impact analysis |
| 3 | `ralph-prompt-multi-task` | PLAN | Generate phased prompts with sequential milestones for multi-task breakdown |
| 4 | `orchestrate` | PLAN | Meta-orchestrate multi-agent workflow across DEFINE→PLAN→BUILD→VERIFY→REVIEW→SHIP |
| 5 | `chain-of-thought` | PLAN | Step-by-step reasoning for architecture decisions and trade-off analysis |
| 6 | `headroom` | PLAN | Assess capacity, constraints, and resource availability before committing to build |
| 7 | `Caveman` | PLAN | Simplest solution first — prevent over-engineering during design |
| 8 | `parallel-agent-skills` | BUILD | Execute multiple agent skills in parallel during implementation |
| 9 | `devils-advocate` | REVIEW | Systematically challenge assumptions, identify failure modes, stress-test before commit |
| 10 | `impeccable` | REVIEW | Full-spectrum quality framework: audit, critique, distill, adapt, optimize, delight, result |

---

## Skill Installation Status

### ✅ Already Installed (~/.agents/skills/)

| Skill | Source | Pipeline Stage |
|-------|--------|---------------|
| `triage` | mattpocock/skills | DEFINE |
| `diagnosing-bugs` | mattpocock/skills | DEFINE |
| `grill-with-docs` | mattpocock/skills | PLAN |
| `grilling` | mattpocock/skills | PLAN |
| `domain-modeling` | mattpocock/skills | PLAN |
| `to-spec` | mattpocock/skills | PLAN |
| `ponytail` | DietrichGebert/ponytail | PLAN |
| `grill-with-tail` | andre-lmarinho/grillwith-tail | PLAN |
| `grill-powers` | okht/grill-powers | PLAN/SHIP |
| `writing-plans` | hazikkhatri/superpowers | BUILD |
| `subagent-driven-development` | hazikkhatri/superpowers | BUILD |
| `executing-plans` | hazikkhatri/superpowers | BUILD |
| `systematic-debugging` | hazikkhatri/superpowers | BUILD/VERIFY |
| `verification-before-completion` | hazikkhatri/superpowers | VERIFY |
| `finishing-a-development-branch` | hazikkhatri/superpowers | REVIEW/SHIP |
| `agent-run` | GRD-Chang/grill-engineering (pip package) | SHIP |
| `parallel-deep-research` | parallel-web/parallel-agent-skills (skills.sh) | DEFINE |
| `parallel-findall` | parallel-web/parallel-agent-skills (skills.sh) | DEFINE |
| `github-research` | lingzhi227/agent-research-skills | DEFINE |
| `free-search-aggregator` | vulcanusalex/free-search-aggregator | DEFINE |
| `freeUnlimited-websearch` | lngu/openclaw-skill-freeunlimited-websearch | DEFINE |
| `you-web` | youdotcom-oss/agent-skills | DEFINE |
| `agent-skills` | Custom stub (`skills/agent-skills/`) | DEFINE |
| `codemap` | Custom stub (`skills/codemap/`) | DEFINE |
| `ralph-prompt-multi-task` | Custom stub (`skills/ralph-prompt-multi-task/`) | PLAN |
| `orchestrate` | Custom stub (`skills/orchestrate/`) | PLAN |
| `chain-of-thought` | Custom stub (`skills/chain-of-thought/`) | PLAN |
| `headroom` | Custom stub (`skills/headroom/`) | PLAN |
| `Caveman` | Custom stub (`skills/Caveman/`) | PLAN |
| `parallel-agent-skills` | Custom stub (`skills/parallel-agent-skills/`) | BUILD |
| `devils-advocate` | Custom stub (`skills/devils-advocate/`) | REVIEW |
| `impeccable` | Custom stub (`skills/impeccable/`) | REVIEW |

### 📦 Install commands (research stack)

```bash
npx skills add parallel-web/parallel-agent-skills --skill parallel-deep-research --skill parallel-findall --agent '*' -y
npx skills add lingzhi227/agent-research-skills --skill github-research --agent '*' -y
npx skills add https://github.com/vulcanusalex/free-search-aggregator --skill free-search-aggregator --agent '*' -y
npx skills add https://github.com/lngu/openclaw-skill-freeunlimited-websearch --skill freeUnlimited-websearch --agent '*' -y
npx skills add https://github.com/youdotcom-oss/agent-skills --skill you-web --agent '*' -y
```

### ❌ Still not published anywhere (gap)

| Skill | Status |
|-------|--------|
| `meta-skill` | Not found in vercel-labs/skills, mattpocock/skills, or parallel-web/parallel-agent-skills |
| `code-review` | mattpocock/skills engineering — available but not yet installed |
| `brainstorming` | obra/superpowers — available but not yet installed |
| `agent-reach` | Not found in any major skill repository |
| `duckduckgo-search` | Not found as a published skill |
| `exa-web-search-free` | Not found as a published skill |

---

## The 10 Pipelines

Each pipeline flows: **DEFINE → PLAN → BUILD → VERIFY → REVIEW → SHIP**

| # | Pipeline | Stack 1 Job | End-to-End Skill Flow |
|---|----------|-------------|----------------------|
| **1** | **Bug Fix** | Fix a bug — Something is broken | `triage` → `diagnosing-bugs` → `systematic-debugging` → `writing-plans` → `executing-plans` → `verification-before-completion` → `finishing-a-development-branch` |
| **2** | **Feature Development** | New feature — You want something new | `agent-skills` → `codemap` → `grill-me` → `grilling` → `domain-modeling` → `to-spec` → `grill-powers` → `ralph-prompt-multi-task` → `chain-of-thought` → `headroom` → `Caveman` → `writing-plans` → `executing-plans` → `parallel-agent-skills` → `verification-before-completion` → `devils-advocate` → `impeccable` → `finishing-a-development-branch` |
| **3** | **Security Fix** | Something isn't safe | `triage` → `diagnosing-bugs` → `systematic-debugging` → `writing-plans` → `executing-plans` → `verification-before-completion` → `devils-advocate` → `impeccable` → `finishing-a-development-branch` |
| **4** | **Performance Optimization** | It's too slow | `triage` → `diagnosing-bugs` → `systematic-debugging` → `writing-plans` → `executing-plans` → `verification-before-completion` → `devils-advocate` → `impeccable` → `finishing-a-development-branch` |
| **5** | **Documentation & Spec** | Write instructions — People need to understand it | `agent-skills` → `codemap` → `grill-with-docs` → `domain-modeling` → `to-spec` → `ponytail` → `ralph-prompt-multi-task` → `Caveman` → `writing-plans` → `executing-plans` → `parallel-agent-skills` → `verification-before-completion` → `devils-advocate` → `impeccable` → `finishing-a-development-branch` |
| **6** | **Incident Response** | Emergency — Something big broke | `triage` → `diagnosing-bugs` → `systematic-debugging` → `writing-plans` → `executing-plans` → `verification-before-completion` → `devils-advocate` → `impeccable` → `finishing-a-development-branch` |
| **7** | **Refactoring** | Clean up — It's messy | `agent-skills` → `codemap` → `grill-me` → `grilling` → `to-spec` → `chain-of-thought` → `headroom` → `Caveman` → `writing-plans` → `executing-plans` → `parallel-agent-skills` → `verification-before-completion` → `devils-advocate` → `impeccable` → `finishing-a-development-branch` |
| **8** | **Dependency Update** | Update helpers — Tools are old | `agent-skills` → `codemap` → `agent-browser` → `find-skills` → `headroom` → `writing-plans` → `executing-plans` → `parallel-agent-skills` → `verification-before-completion` → `devils-advocate` → `impeccable` → `finishing-a-development-branch` |
| **9** | **Architecture Review** | Big picture — You're changing the design | `agent-skills` → `codemap` → `grill-me` → `grilling` → `domain-modeling` → `to-spec` → `grill-powers` → `ralph-prompt-multi-task` → `chain-of-thought` → `headroom` → `Caveman` → `writing-plans` → `executing-plans` → `parallel-agent-skills` → `verification-before-completion` → `devils-advocate` → `impeccable` → `finishing-a-development-branch` |
| **10** | **Full Product Delivery** | Build new — You're making something from scratch | `agent-skills` → `codemap` → `grill-powers` → `ralph-prompt-multi-task` → `orchestrate` → `chain-of-thought` → `headroom` → `Caveman` → `writing-plans` → `executing-plans` → `subagent-driven-development` → `parallel-agent-skills` → `systematic-debugging` → `verification-before-completion` → `devils-advocate` → `impeccable` → `finishing-a-development-branch` → `agent-run` |

---

## Research Investigation Stack (prepended to DEFINE for research-heavy pipelines)

| Phase | Skills | Role | Source |
|-------|--------|------|--------|
| **Research** | `parallel-deep-research`, `free-search-aggregator`, `freeUnlimited-websearch`, `you-web` | Multi-source web research, aggregated results | parallel-web/parallel-agent-skills, vulcanusalex, lngu, youdotcom-oss |
| **Investigation** | `parallel-findall`, `github-research` | Agent reachability, skill discovery across repos, GitHub repo analysis | parallel-web/parallel-agent-skills, lingzhi227 |
| **Brainstorming** | `brainstorming` (superpowers), `grilling`, `grill-me` | Clarify ideas through Q&A | obra/superpowers, mattpocock/skills |
| **Planning** | `writing-plans`, `to-spec`, `domain-modeling`, `grill-with-docs` | Break into tasks, write PRD, GLOSSARY.md + ADRs | hazikkhatri/superpowers, mattpocock/skills |

**Still missing:** `meta-skill`, `agent-reach`, `duckduckgo-search`, `exa-web-search-free` — not found in any major skill repository.

---

## Decision Gates

| Gate | From Stage | To Stage | Condition |
|------|-----------|----------|-----------|
| G1 | DEFINE | PLAN | Requirements clarified, scope agreed |
| G2 | PLAN | BUILD | PRD approved, tasks broken down, headroom confirmed |
| G3 | BUILD | VERIFY | Implementation complete, tests written |
| G4 | VERIFY | REVIEW | All tests pass, evidence captured |
| G5 | REVIEW | SHIP | Code reviewed, devils-advocate challenged, impeccable quality gate passed |
| G6 | SHIP | Complete | Branch merged or PR closed |

---

## File Locations

- Pipeline definition: `docs/skills-framework/10-PIPELINES.md`
- Framework overview: `docs/skills-framework/README.md`
- Quick reference: `docs/skills-framework/QUICK_REFERENCE.md`
- Skill stubs: `skills/` (10 conceptual skill SKILL.md files)
- Skill installation: `~/.agents/skills/` (26 skills installed: 16 original + 10 research/conceptual)
- Delivery tool: `tools/grill-engineering/` + `agent-run` CLI
- Project config: `AGENTS.md`, `docs/agents/issue-tracker.md`, `docs/agents/domain.md`
