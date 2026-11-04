---
name: Caveman
description: Start with the simplest possible solution that could work, then iterate. Avoid over-engineering by defaulting to minimal viable implementation. Reduces token usage by 60-75% on structured tasks through terse, direct responses.
source: JuliusBrussee/caveman
pipeline_stage: PLAN
---

# Caveman

**Pipeline Stage:** PLAN (Stage 2 – Plan & Architect)

**Purpose:** Prevent over-engineering by insisting on the simplest possible implementation first. Only add complexity when required by demonstrated need. Also reduces agent verbosity, cutting output tokens by 60–75% on structured tasks.

**When to use:** During the PLAN stage for design discussions and architecture reviews. Also useful in BUILD for keeping implementations minimal and focused.

**Intensity levels:**
| Level | Style | Best Use |
|-------|-------|----------|
| lite | Removes filler, keeps grammar | Technical work with high readability |
| full | Standard caveman, shorter sentences | Daily reviews and triage |
| ultra | Maximum compression, telegraphic | Automated pipelines and high volume |

**Process:**
1. State the requirement in the simplest possible terms
2. Propose the most minimal implementation that satisfies it
3. Identify what complexity would be needed for edge cases
4. Defer edge-case complexity until it's actually needed
5. Document the simplicity constraint as a design principle

**Handoff contract:**
- Input: Feature or design requirement
- Output: Minimal viable implementation plan + deferral list
- Handoff to: BUILD stage (writing-plans → executing-plans)

**Install:** Custom skill — create at `skills/Caveman/SKILL.md`
Source: https://github.com/JuliusBrussee/caveman

**Pipeline integration:** Used in pipelines #2, #5, #7, #9, #10 during PLAN to prevent over-engineering.
