---
name: compare-a-b
description: Weighted A/B comparison for choosing between technologies, approaches, or vendors. Use when two or more options must be ranked on shared criteria: score each dimension, show the arithmetic, and name when the loser is the better choice.
source: owl-agent-proxy (migrated from a flat prompt file)
pipeline_stage: PLAN
---

# compare-a-b

## Context
Structured A/B comparison with weighted scoring. Use when choosing between technologies, approaches, or vendors.

## Instructions
1. Define evaluation criteria (3–7 dimensions)
2. Score each option 1–5 per dimension
3. Weight dimensions by user priority (default: equal)
4. Calculate weighted score
5. Present: markdown table + winner + "when to choose the loser"

## Constraints
- Never declare a winner without showing the math
- Include a "hidden cost" row most people overlook
- If scores are within 10%, call it a tie and explain context-dependent choice

## Examples
**Input:** "Compare Bright Data vs Oxylabs"
**Output:** Table with: pricing, proxy types, success rate, documentation, support, ethics — weighted by enterprise vs. startup needs
