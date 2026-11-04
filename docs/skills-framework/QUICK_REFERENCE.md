# Skills Framework — Quick Reference

**At-a-glance reference** for the 10 end-to-end use-case pipelines, common commands, and skill lookup.

**Operating Instructions:** smp5.4pd.md — Mode: 🚀 Speed

---

## 10 Pipelines at a Glance

| # | Pipeline | Trigger | Flow (abbreviated) |
|---|----------|---------|-------------------|
| 1 | Bug Fix | Something is broken | triage → diagnose → debug → plan → implement → verify → release |
| 2 | Feature Development | You want something new | clarify → spec → approve → plan → implement → verify → release |
| 3 | Security Fix | Something isn't safe | triage → diagnose → debug → plan → implement → verify → release |
| 4 | Performance Optimization | It's too slow | triage → diagnose → debug → plan → implement → verify → release |
| 5 | Documentation & Spec | People need to understand it | document → model → spec → plan → implement → verify → release |
| 6 | Incident Response | Something big broke | triage → diagnose → debug → plan → implement → verify → release |
| 7 | Refactoring | It's messy | clarify → spec → plan → implement → verify → release |
| 8 | Dependency Update | Tools are old | assess → plan → implement → verify → release |
| 9 | Architecture Review | You're changing the design | clarify → model → spec → plan → implement → verify → release |
| 10 | Full Product Delivery | You're making something from scratch | approve → plan → implement → debug → verify → release → automate |

---

## Stage → Skill Lookup

| Stage | Skills |
|-------|--------|
| DEFINE | triage, diagnosing-bugs, grill-me, grilling, find-skills, agent-browser, grill-with-docs |
| PLAN | domain-modeling, to-spec, grill-powers, grill-with-tail, ponytail |
| BUILD | writing-plans, executing-plans, subagent-driven-development, systematic-debugging |
| VERIFY | verification-before-completion, systematic-debugging |
| REVIEW | code-review, finishing-a-development-branch |
| SHIP | agent-run, finishing-a-development-branch |

---

## Research Stack (install before use)

```bash
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
| G2 | PLAN → BUILD | PRD approved |
| G3 | BUILD → VERIFY | Code + tests done |
| G4 | VERIFY → REVIEW | Tests pass |
| G5 | REVIEW → SHIP | Review approved |
| G6 | SHIP → Complete | Merged / closed |

---

## Verification

```bash
python -m pytest tests/ -q                                    # Test suite (484 passed, 83% coverage)
python scripts/verify-install.py --owl-home <path> --no-live  # Install verify (18 PASS, 0 FAIL, 2 SKIP)
agent-run doctor                                              # Delivery tool readiness
```

---

## File Locations

- Full framework: `docs/skills-framework/README.md`
- Pipeline definition: `docs/skills-framework/10-PIPELINES.md`
- Research skill: `~/.agents/skills/research-investigation-pipeline/SKILL.md`
- Project config: `AGENTS.md`
