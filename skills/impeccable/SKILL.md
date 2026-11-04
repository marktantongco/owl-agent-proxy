---
name: impeccable
description: Full-spectrum quality and excellence framework for code and deliverables. Audit, critique, distill, adapt, optimize, delight, and produce results. Sub-skills: impeccable-audit, impeccable-critique, impeccable-distill, impeccable-adapt, impeccable-optimize, impeccable-delight, impeccable-result.
pipeline_stage: REVIEW
---

# impeccable

**Pipeline Stage:** REVIEW (Stage 3 – Review)

**Purpose:** Apply a full-spectrum quality framework to code and deliverables. Seven sub-skills cover the complete quality lifecycle from audit to measurable results.

**Sub-skills:**
| Sub-skill | Purpose |
|-----------|---------|
| impeccable-audit | Audit code quality, security, and standards compliance |
| impeccable-critique | Critique implementation decisions and alternatives |
| impeccable-distill | Distill deliverables to essentials, removing noise |
| impeccable-adapt | Adapt solutions to constraints and edge cases |
| impeccable-optimize | Optimize performance, cost, and resource usage |
| impeccable-delight | Improve user experience and polish |
| impeccable-result | Produce measurable outcomes and evidence |

**When to use:** During the REVIEW stage for pre-release quality gates, code review, refactoring validation, performance tuning, any point where excellence is required before SHIP.

**Handoff contract:**
- Input: Code or deliverable + quality criteria
- Output: Quality report with findings and recommendations
- Handoff to: SHIP stage (agent-run → finishing-a-development-branch) — only if quality gates pass

**Install:** Custom skill — create at `skills/impeccable/SKILL.md`

**Pipeline integration:** Used in pipelines #2, #3, #4, #5, #6, #7, #8, #9, #10 during REVIEW as the final quality gate before SHIP.
