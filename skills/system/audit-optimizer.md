# Skill: audit-optimizer

## Context
Profile → diagnose → fix → verify optimization loops. Use when performance is slow, queries are lagging, or resources are constrained.

## Instructions
1. **Capture baseline** — measure before touching anything
2. **Identify bottleneck** — use EXPLAIN ANALYZE, profilers, or tracing
3. **Apply ONE change** — never change 2 things at once
4. **Re-measure** — did it improve? If not, revert.
5. **Document** — what was the bottleneck, what fixed it, what to monitor

## Constraints
- Profile BEFORE optimizing. No exceptions.
- If the bottleneck is not where you expected, report the surprise.
- Optimization without measurement is guessing.

## Examples
**Input:** "My scraper is slow"
**Output:** Check cache hit ratio → check dedup map size → check proxy response time → check rate limit queue depth → fix the actual bottleneck
