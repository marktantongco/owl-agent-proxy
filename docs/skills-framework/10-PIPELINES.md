# 10 End-to-End Use-Case Pipelines

**Consolidated from stacks 1–5:** phase skills, 10 use-case pipelines, DEFINE/PLAN/BUILD/VERIFY/REVIEW/SHIP stage mapping, research investigation stack.

**Operating Instructions:** smp5.4pd.md (Tactical Merge) — Mode: 🐜 Systematic

---

## Consolidated Stage-to-Skill Mapping

| Pipeline Stage | Deployment Stage | Skills |
|----------------|------------------|--------|
| **DEFINE** | Stage 1 – Discover & Research | `find-skills`, `agent-browser`, `grill-me`, `grilling`, `parallel-deep-research`, `duckduckgo-search`, `exa-web-search-free`, `free-search-aggregator`, `freeUnlimited-websearch`, `you-web`, `agent-reach`, `github-research` *(meta-skill: NOT FOUND — gap documented)* |
| **PLAN** | Stage 2 – Plan & Architect | `domain-modeling`, `to-spec`, `grill-with-docs`, `grill-with-tail`, `grill-powers`, `ponytail`, `brainstorming`, `ralph-prompt-multi-task`, `orchestrate`, `chain-of-thought`, `headroom`, `Caveman`, `devils-advocate`, `codemap`, `parallel-agent-skills`, `agent-skills`, `impeccable` *(10 conceptual skills: custom stubs created locally)* |
| **BUILD** | Stage 3 – Execute | `writing-plans`, `executing-plans`, `subagent-driven-development`, `systematic-debugging` |
| **VERIFY** | Stage 3 – Verify | `verification-before-completion`, `systematic-debugging` |
| **REVIEW** | Stage 3 – Review | `code-review`, `finishing-a-development-branch` |
| **SHIP** | Stage 3 – Ship | `agent-run` (grill-engineering CLI), `finishing-a-development-branch` |

---

## Skill Installation Status

### ✅ Already Installed (~/.agents/skills/)

| Skill | Source |
|-------|--------|
| `triage` | mattpocock/skills |
| `diagnosing-bugs` | mattpocock/skills |
| `grill-with-docs` | mattpocock/skills |
| `grilling` | mattpocock/skills |
| `domain-modeling` | mattpocock/skills |
| `to-spec` | mattpocock/skills |
| `ponytail` | DietrichGebert/ponytail |
| `grill-with-tail` | andre-lmarinho/grillwith-tail |
| `grill-powers` | okht/grill-powers |
| `writing-plans` | hazikkhatri/superpowers |
| `subagent-driven-development` | hazikkhatri/superpowers |
| `executing-plans` | hazikkhatri/superpowers |
| `systematic-debugging` | hazikkhatri/superpowers |
| `verification-before-completion` | hazikkhatri/superpowers |
| `finishing-a-development-branch` | hazikkhatri/superpowers |
| `agent-run` | GRD-Chang/grill-engineering (pip package) |
| `parallel-deep-research` | parallel-web/parallel-agent-skills (skills.sh) |
| `parallel-findall` | parallel-web/parallel-agent-skills (skills.sh) |
| `github-research` | lingzhi227/agent-research-skills |
| `free-search-aggregator` | vulcanusalex/free-search-aggregator |
| `freeUnlimited-websearch` | lngu/openclaw-skill-freeunlimited-websearch |
| `you-web` | youdotcom-oss/agent-skills |
| `ralph-prompt-multi-task` | Custom stub (local) |
| `orchestrate` | Custom stub (local) |
| `chain-of-thought` | Custom stub (local) |
| `headroom` | Custom stub (local) |
| `Caveman` | Custom stub (local) |
| `devils-advocate` | Custom stub (local) |
| `codemap` | Custom stub (local) |
| `parallel-agent-skills` | Custom stub (local) |
| `agent-skills` | Custom stub (local) |
| `impeccable` | Custom stub (local) |

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
| **2** | **Feature Development** | New feature — You want something new | `grill-me` → `grilling` → `domain-modeling` → `to-spec` → `grill-powers` → `writing-plans` → `executing-plans` → `verification-before-completion` → `finishing-a-development-branch` |
| **3** | **Security Fix** | Something isn't safe | `triage` → `diagnosing-bugs` → `systematic-debugging` → `writing-plans` → `executing-plans` → `verification-before-completion` → `finishing-a-development-branch` |
| **4** | **Performance Optimization** | It's too slow | `triage` → `diagnosing-bugs` → `systematic-debugging` → `writing-plans` → `executing-plans` → `verification-before-completion` → `finishing-a-development-branch` |
| **5** | **Documentation & Spec** | Write instructions — People need to understand it | `grill-with-docs` → `domain-modeling` → `to-spec` → `ponytail` → `writing-plans` → `executing-plans` → `verification-before-completion` → `finishing-a-development-branch` |
| **6** | **Incident Response** | Emergency — Something big broke | `triage` → `diagnosing-bugs` → `systematic-debugging` → `writing-plans` → `executing-plans` → `verification-before-completion` → `finishing-a-development-branch` |
| **7** | **Refactoring** | Clean up — It's messy | `grill-me` → `grilling` → `to-spec` → `writing-plans` → `executing-plans` → `verification-before-completion` → `finishing-a-development-branch` |
| **8** | **Dependency Update** | Update helpers — Tools are old | `agent-browser` → `find-skills` → `writing-plans` → `executing-plans` → `verification-before-completion` → `finishing-a-development-branch` |
| **9** | **Architecture Review** | Big picture — You're changing the design | `grill-me` → `grilling` → `domain-modeling` → `to-spec` → `grill-powers` → `writing-plans` → `executing-plans` → `verification-before-completion` → `finishing-a-development-branch` |
| **10** | **Full Product Delivery** | Build new — You're making something from scratch | `grill-powers` → `writing-plans` → `executing-plans` → `subagent-driven-development` → `systematic-debugging` → `verification-before-completion` → `finishing-a-development-branch` → `agent-run` |

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
| G2 | PLAN | BUILD | PRD approved, tasks broken down |
| G3 | BUILD | VERIFY | Implementation complete, tests written |
| G4 | VERIFY | REVIEW | All tests pass, evidence captured |
| G5 | REVIEW | SHIP | Code reviewed, approved for merge |
| G6 | SHIP | Complete | Branch merged or PR closed |

---

## File Locations

- Pipeline definition: `docs/skills-framework/10-PIPELINES.md`
- Framework overview: `docs/skills-framework/README.md`
- Quick reference: `docs/skills-framework/QUICK_REFERENCE.md`
- Skill installation: `~/.agents/skills/` (26 skills installed: 16 original + 10 research/conceptual)
- Delivery tool: `tools/grill-engineering/` + `agent-run` CLI
- Project config: `AGENTS.md`, `docs/agents/issue-tracker.md`, `docs/agents/domain.md`
