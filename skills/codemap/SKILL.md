---
name: codemap
description: Map codebase structure — modules, dependencies, entry points, and architectural boundaries — to support navigation and impact analysis. Produces a structural map of modules, dependencies, entry points, data flow, and architectural boundaries.
pipeline_stage: DEFINE
---

# codemap

**Pipeline Stage:** DEFINE (Stage 1 – Discover & Research)

**Purpose:** Produce a structural map of a codebase: modules, dependencies, entry points, data flow, and architectural boundaries. Supports navigation and change impact analysis before planning.

**When to use:** During the DEFINE stage before making large changes, onboarding to a new codebase, or analyzing blast radius of a proposed change. Especially useful in pipelines #2 (Feature Development), #7 (Refactoring), #8 (Dependency Update), #9 (Architecture Review), and #10 (Full Product Delivery).

**Process:**
1. Inventory modules, packages, and their responsibilities
2. Map dependencies between modules (import graph)
3. Identify entry points (APIs, CLI, event handlers)
4. Trace data flow through critical paths
5. Document architectural boundaries and invariant locations

**Handoff contract:**
- Input: Codebase path or repo URL + change scope
- Output: Structural map (modules, dependencies, entry points, boundaries, data flow)
- Handoff to: PLAN stage (domain-modeling → to-spec)

**Install:** Custom skill — create at `skills/codemap/SKILL.md`

**Pipeline integration:** Used in pipelines #2, #7, #8, #9, #10 during DEFINE to understand the codebase before planning.
