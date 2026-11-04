---
name: parallel-agent-skills
description: Execute multiple agent skills in parallel when they operate on independent concerns, then aggregate results. Reduces total execution time by running independent skills concurrently.
pipeline_stage: BUILD
---

# parallel-agent-skills

**Pipeline Stage:** BUILD (Stage 3 – Execute)

**Purpose:** Run multiple agent skills concurrently when their inputs and outputs are independent, reducing total execution time during implementation.

**When to use:** During the BUILD stage when multiple skills can be applied to the same input without dependency on each other (e.g., research + code-review + security-audit in parallel during implementation).

**Process:**
1. Identify skills with independent inputs/outputs
2. Dispatch each skill in parallel with full context
3. Wait for all to complete
4. Aggregate results, handling any conflicts
5. Return combined output

**Handoff contract:**
- Input: Task + list of independent skills
- Output: Aggregated results from all skills
- Handoff to: VERIFY stage (verification-before-completion)

**Install:** Custom skill — create at `skills/parallel-agent-skills/SKILL.md`

**Pipeline integration:** Used in pipelines #2, #5, #7, #9, #10 during BUILD to run multiple skills concurrently.
