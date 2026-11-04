---
name: ralph-prompt-multi-task
description: Generate Ralph-compatible phased prompts for multiple related tasks. Creates phased prompts with sequential milestones, cumulative progress tracking, and phase-based completion promises. Use for CRUD implementations, multi-step features, staged migrations, or any work requiring multiple distinct but related tasks.
source: adaptationio/skrillz
pipeline_stage: PLAN
---

# ralph-prompt-multi-task

**Pipeline Stage:** PLAN (Stage 2 – Plan & Architect)

**Purpose:** Decompose a complex multi-part request into phased, sequential sub-tasks with milestone tracking and cumulative progress. Generates Ralph-compatible prompts that break work into phases, each with its own objectives, dependencies, verification criteria, and completion promises.

**When to use:** During the PLAN stage when you need to break an approved design into executable phases. Ideal for CRUD implementations, multi-step features, staged migrations, API endpoint suites, test suite creation, and multi-file refactoring.

**Process:**
1. Map the tasks — create a task inventory with name, dependencies, verification criteria, and estimated complexity
2. Group tasks into phases (foundation, core, integration, polish, etc.)
3. Generate phase-based prompts with sequential milestones
4. Define cumulative progress tracking across phases
5. Set completion promises for each phase and the overall objective

**Handoff contract:**
- Input: Approved PRD/spec, task list with dependencies
- Output: Phase-structured prompt template with milestones, verification criteria, and completion criteria
- Handoff to: BUILD stage (writing-plans → executing-plans)

**Ralph philosophy:** Failures are deterministic and fixable. Each phase iteration learns from previous attempts. Don't fear failures — they provide data for improvement through prompt tuning.

**Install:** Custom skill — create at `skills/ralph-prompt-multi-task/SKILL.md`
Or install from source: `pnpm dlx add-skill https://github.com/adaptationio/skrillz/ralph-prompt-multi-task`

**Pipeline integration:** Used in pipelines #2 (Feature Development), #5 (Documentation & Spec), #7 (Refactoring), #9 (Architecture Review), #10 (Full Product Delivery) during the PLAN stage.
