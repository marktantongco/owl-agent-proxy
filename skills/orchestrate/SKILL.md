---
name: orchestrate
description: Coordinate multiple sub-agents across a multi-stage pipeline, managing dependencies, handoffs, and aggregate progress. Acts as a meta-orchestrator for DEFINE → PLAN → BUILD → VERIFY → REVIEW → SHIP workflows.
pipeline_stage: PLAN
---

# orchestrate

**Pipeline Stage:** PLAN (Stage 2 – Plan & Architect)

**Purpose:** Act as a meta-orchestrator for multi-agent workflows. Map the full workflow into stages with dependencies, assign each stage to the appropriate agent/skill, manage handoff contracts between stages, monitor progress, and handle failures/retries.

**When to use:** Complex workflows requiring coordination across multiple agents or stages. Especially useful for pipelines #2 (Feature Development), #9 (Architecture Review), and #10 (Full Product Delivery) where multiple skills must be sequenced and coordinated.

**Process:**
1. Map the full workflow into stages with dependencies (DEFINE → PLAN → BUILD → VERIFY → REVIEW → SHIP)
2. Assign each stage to the appropriate agent/skill based on the pipeline's skill flow
3. Manage handoff contracts between stages (input → output transformation)
4. Monitor progress across all sub-agents and stages
5. Handle failures, retries, and stage gate decisions (G1–G6)

**Handoff contract:**
- Input: Workflow definition with stages, dependencies, and skill assignments
- Output: Coordinated execution with per-stage results and gate decisions
- Handoff to: BUILD stage (writing-plans → executing-plans)

**Decision gates managed:** G1 (DEFINE→PLAN), G2 (PLAN→BUILD), G3 (BUILD→VERIFY), G4 (VERIFY→REVIEW), G5 (REVIEW→SHIP), G6 (SHIP→Complete)

**Install:** Custom skill — create at `skills/orchestrate/SKILL.md`

**Pipeline integration:** Used in all 10 pipelines as the meta-coordinator between stages.
