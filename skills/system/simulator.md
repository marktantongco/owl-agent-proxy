# Skill: simulator

## Context
End-to-end interaction tracing before code generation. Use when building UI, APIs, or multi-step workflows.

## Instructions
1. Map every user action → system state → expected output
2. Trace: happy path, edge cases, error paths, recovery paths
3. If you cannot trace every row, do not generate code
4. Present as a markdown table: Step | Action | State | Output | Edge | Recovery

## Constraints
- Never skip the error path trace
- Never skip the recovery trace
- If an interaction has >7 steps, break it into sub-flows

## Examples
**Input:** "Build a login flow"
**Output:** Table tracing: load page → enter credentials → submit → validate → 2FA → redirect → session — with edge cases for each
