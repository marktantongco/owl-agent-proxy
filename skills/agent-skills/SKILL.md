---
name: agent-skills
description: Generic agent skills framework — discover, install, and manage skills across the skills.sh ecosystem and direct GitHub sources. Provides the foundation for the skills pipeline framework itself.
pipeline_stage: DEFINE
---

# agent-skills

**Pipeline Stage:** DEFINE (Stage 1 – Discover & Research)

**Purpose:** Provide a generic framework for discovering, installing, and managing agent skills from the skills.sh ecosystem and direct GitHub sources. Foundation for the skills pipeline framework.

**When to use:** During the DEFINE stage when you need to find or install a skill for a specific task, or manage the skill inventory across the pipeline.

**Process:**
1. Search skills.sh or GitHub for skills matching the task domain
2. Evaluate quality by install count, source reputation, stars, and SKILL.md completeness
3. Install via `npx skills add <owner>/<repo> --skill <name> --agent '*' -y`
4. Verify the skill is available in the agent's skill directory
5. Document the skill in the project inventory

**Install commands:**
```bash
npx skills add <owner>/<repo> --skill <skill-name> --agent '*' -y
```

**Handoff contract:**
- Input: Task domain or skill name
- Output: Installed skill ready for use
- Handoff to: PLAN stage (domain-modeling → to-spec)

**Install:** Custom skill — create at `skills/agent-skills/SKILL.md`

**Pipeline integration:** Used in pipelines #2, #5, #7, #8, #9, #10 during DEFINE to discover and install needed skills.
