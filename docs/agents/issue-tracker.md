# Issue Tracker Configuration

## Format

Issues are tracked in GitHub issues with the following labels:

| Label | Meaning |
|-------|---------|
| `bug` | Something isn't working |
| `enhancement` | New feature or improvement |
| `documentation` | Docs only |
| `priority/high` | Must fix before next release |
| `priority/medium` | Should fix before next release |
| `priority/low` | Nice to have |
| `protocol/escalation` | Requires protocol escalation justification |
| `config/schema` | Config schema change |

## Workflow

1. Triage: Use `triage` skill to grill vague reports into workable items
2. Diagnose: Use `diagnosing-bugs` skill for bug investigation
3. Plan: Use `grill-powers` → `to-spec` → `writing-plans` for feature work
4. Execute: Use `subagent-driven-development` or `executing-plans`
5. Verify: Use `verification-before-completion` + `finishing-a-development-branch`

## RECORD-FORMAT

Each issue record includes:

- Title: concise, action-oriented
- Body: problem, expected behavior, actual behavior, steps to reproduce
- Labels: from the table above
- Assignee: optional, defaults to unassigned
