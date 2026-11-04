---
name: meta-skill
description: Meta-skill for discovering and installing other skills from the skills.sh ecosystem. Serves as the discovery layer — when the agent doesn't know how to do something, use this skill to find and install the right capability.
source: vercel-labs/skills
pipeline_stage: DEFINE
---

# meta-skill

**Pipeline Stage:** DEFINE (Stage 1 – Discover & Research)

**Purpose:** Discover and install agent skills from the skills.sh ecosystem. When the agent encounters a task it cannot handle with currently installed skills, use this skill to find and install the right capability mid-task.

**When to use:** Before starting any task where the required capability is not already installed. Check the skills.sh leaderboard first for well-known skills with high install counts.

**Process:**
1. Search skills.sh for skills matching the task domain using `npx skills find [query]`
2. Check install count (1K+ preferred) and source reputation
3. Install via `npx skills add <owner>/<repo> --skill <name> --agent '*' -y`
4. Verify the skill is available in the agent's skill directory
5. Document the skill in the project inventory

**Install commands:**
```bash
npx skills add vercel-labs/skills --skill find-skills --agent '*' -y
npx skills add <owner>/<repo> --skill <skill-name> --agent '*' -y
```

**Handoff contract:**
- Input: Task domain or skill name needed
- Output: Installed skill ready for use
- Handoff to: PLAN stage (domain-modeling → to-spec)

**Source:** https://www.skills.sh/vercel-labs/skills/find-skills

**Pipeline Integration:** Used in DEFINE stage of pipelines #2, #5, #7, #8, #9, #10.
