# Skill: brainstorm

## Context
Divergent thinking, constraint relaxation, and idea generation. Use when the user is stuck, needs alternatives, or is optimizing a single-path solution.

## Instructions
1. State the constraint set explicitly
2. Generate 5+ distinct approaches (do not self-censor)
3. For each: list pros, cons, and a "what if we removed constraint X?" variant
4. Rank by impact × feasibility
5. Present in markdown table

## Constraints
- Never present only one option unless explicitly asked
- The "crazy" option often contains the seed of the best solution
- Include at least one option that inverts the problem

## Examples
**Input:** "How do I make my scraper faster?"
**Output:** Table with: (1) Add proxies, (2) Cache responses, (3) Parallelize requests, (4) Use headless browser less, (5) Invert: scrape less, API more
