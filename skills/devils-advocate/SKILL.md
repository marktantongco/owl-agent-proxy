---
name: devils-advocate
description: Systematically challenges decisions, plans, architectures, and code by arguing the opposing side. Surfaces risks, pokes holes in assumptions, and stress-tests thinking before committing. Supports intensity levels (gentle, balanced, ruthless, linus).
source: Multiple implementations (lobehub/bidodev, Cold-IQ, richiethomas)
pipeline_stage: REVIEW
---

# devils-advocate

**Pipeline Stage:** REVIEW (Stage 3 – Review)

**Purpose:** Act as a critical reviewer who systematically challenges assumptions, identifies failure modes, and stress-tests proposed approaches before commitment. Exposes blind spots, accelerates safer decision-making, and produces actionable fixes.

**When to use:** During the REVIEW stage for pre-merge code reviews, architecture decision reviews, product strategy stress-tests, incident postmortem challenges, and design trade-off analysis. Can also be used in PLAN to stress-test designs before G2 (PLAN→BUILD gate).

**Severity levels:**
| Level | Style | Use Case |
|-------|-------|----------|
| gentle | Collaborative critique | Early-stage design discussions |
| balanced | Balanced risk assessment | Standard pre-merge reviews |
| ruthless | Aggressive flaw-finding | High-stakes architecture decisions |
| linus | Linus Torvalds-style evisceration | Critical security or correctness issues |

**Process:**
1. State the proposed approach and its key assumptions
2. Challenge each assumption with counter-evidence or alternative interpretations
3. Identify failure modes (what could go wrong, how, and how badly)
4. Propose mitigation strategies or alternative approaches
5. Deliver a risk assessment with confidence levels

**Handoff contract:**
- Input: Proposed approach, design, or code diff + assumptions
- Output: Challenge log + failure modes + risk assessment + remediation suggestions
- Handoff to: SHIP stage (if approved) or back to PLAN/BUILD (if rework needed)

**Install:** Custom skill — create at `skills/devils-advocate/SKILL.md`
Sources: https://lobehub.com/skills/bidodev-devils-advocate-skill-devils-advocate, https://github.com/richiethomas/claude-devils-advocate

**Pipeline integration:** Used in pipelines #2, #3, #4, #5, #6, #7, #8, #9, #10 during REVIEW to challenge implementations before SHIP.
