---
name: headroom
description: Assess capacity, constraints, and resource availability before committing to a plan or timeline. Identifies bottlenecks, skill gaps, and constraint risks early in the planning process.
pipeline_stage: PLAN
---

# headroom

**Pipeline Stage:** PLAN (Stage 2 – Plan & Architect)

**Purpose:** Evaluate whether the team/system has sufficient capacity (time, skills, compute, dependencies) to take on a proposed body of work. Identify bottlenecks and constraint risks before committing to implementation.

**When to use:** During the PLAN stage before committing to sprint plans, feature estimates, or release dates. Especially useful in pipelines #2 (Feature Development), #8 (Dependency Update), #9 (Architecture Review), and #10 (Full Product Delivery).

**Process:**
1. Inventory available resources (person-hours, compute, dependencies, tooling)
2. Assess current commitments and utilization across all pipelines
3. Identify constraint risks (single points of failure, skill gaps, dependency bottlenecks)
4. Compute realistic capacity for new work
5. Recommend scope adjustment or timeline extension if headroom is insufficient

**Handoff contract:**
- Input: Proposed work + resource inventory + current commitments
- Output: Capacity assessment + risk flags + scope/timeline recommendations
- Handoff to: BUILD stage (writing-plans → executing-plans) — only if headroom is sufficient

**Install:** Custom skill — create at `skills/headroom/SKILL.md`

**Pipeline integration:** Used in pipelines #2, #8, #9, #10 during PLAN as a gate before BUILD.
